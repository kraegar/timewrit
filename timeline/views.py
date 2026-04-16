import io
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db import models
from django.db.models import Q
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from .models import TimelineEvent, Location, Person, Timeline, PersonRelationship, Source, Tag, Story, StoryEvent, format_date_with_precision, PublicComment, Attachment, HelpCategory, HelpTopic
from .importers.csv_importer import EventImporter, PersonImporter, LocationImporter
from .serializers import serialize_event, serialize_person, serialize_story, serialize_location
from django_ratelimit.decorators import ratelimit
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.utils.text import slugify
from datetime import datetime
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_cookie
from collections import defaultdict
from django.contrib.auth.decorators import user_passes_test
from django.utils.html import strip_tags



# ---------------------------------------------------------------------------
# Help System Views
# ---------------------------------------------------------------------------

def help_index(request):
    """
    Landing page for help documenting all features.
    """
    categories = HelpCategory.objects.prefetch_related('topics').all()
    return render(request, 'timeline/help_index.html', {'categories': categories})

def help_topic_detail(request, slug):
    """
    Detail page for a specific help topic.
    """
    topic = get_object_or_404(HelpTopic, slug=slug, is_published=True)
    categories = HelpCategory.objects.prefetch_related('topics').all()
    return render(request, 'timeline/help_topic.html', {
        'topic': topic,
        'categories': categories
    })


def person_detail_json(request, person_id):
    """
    Returns a freshly serialized Person object for the given ID.
    Used by the frontend to fetch current person data on demand when clicking
    a person card, bypassing the stale JS dict built at page load.
    """
    person = get_object_or_404(Person, pk=person_id)
    if person.is_private and not request.user.is_authenticated:
        return JsonResponse({'error': 'Private person'}, status=403)
    sources_cache = {}
    data = serialize_person(person, sources_cache=sources_cache, request_user=request.user)
    return JsonResponse({'person': data, 'sources': list(sources_cache.values())})

def location_detail_json(request, location_id):
    """
    Returns a freshly serialized Location object for the given ID.
    Used by the frontend to fetch current location data on demand.
    """
    location = get_object_or_404(Location, pk=location_id)
    if location.is_private and not request.user.is_authenticated:
        return JsonResponse({'error': 'Private location'}, status=403)
    sources_cache = {}
    data = serialize_location(location, sources_cache=sources_cache, request_user=request.user)
    return JsonResponse({'location': data, 'sources': list(sources_cache.values())})


def index(request):
    """
    Main view for the timeline application.
    """
    locations = Location.objects.select_related('parent', 'owner').all().order_by('name')
    people = Person.objects.select_related('owner').all().order_by('name')
    timelines = Timeline.objects.select_related('owner', 'parent').all().order_by('owner__username', 'name')
    tags = Tag.objects.all().order_by('name')
    stories = Story.objects.select_related('owner').all().order_by('title')

    if not request.user.is_authenticated:
        locations = locations.exclude(is_private=True)
        people = people.exclude(is_private=True)
        timelines = timelines.exclude(is_private=True)
        stories = stories.exclude(is_private=True)

    return render(request, 'timeline/index.html', {
        'locations': locations,
        'people': people,
        'timelines': timelines,
        'tags': tags,
        'stories': stories,
    })

def _collect_child_ids(parent, id_set):
    """
    Recursively adds all child IDs of ``parent`` to ``id_set``.
    Used by the timeline and location expansion helpers.
    """
    for child in parent.children.all():
        id_set.add(child.id)
        _collect_child_ids(child, id_set)


def _get_expanded_timelines(timeline_ids):
    """
    Given a list of timeline IDs, returns a set of those IDs plus all
    descendant (child) timeline IDs so that sub-timelines are always included.
    """
    all_timeline_ids = set()
    for tl_id in timeline_ids:
        try:
            timeline = Timeline.objects.get(id=tl_id)
            all_timeline_ids.add(timeline.id)
            _collect_child_ids(timeline, all_timeline_ids)
        except Timeline.DoesNotExist:
            pass
    return all_timeline_ids


def _get_expanded_locations(location_ids):
    """
    Given a list of location IDs, returns a set of those IDs plus all
    descendant (child) location IDs.
    """
    all_location_ids = set()
    for loc_id in location_ids:
        try:
            location = Location.objects.get(id=loc_id)
            all_location_ids.add(location.id)
            _collect_child_ids(location, all_location_ids)
        except Location.DoesNotExist:
            pass
    return all_location_ids

def _get_filtered_events(request):
    """
    Shared helper to filter events based on request parameters.
    """
    # Privacy filtering: base entity scopes
    events_qs = TimelineEvent.objects.all()
    people_qs = Person.objects.all()
    location_qs = Location.objects.all()

    if not request.user.is_authenticated:
        events_qs = events_qs.exclude(is_private=True)
        people_qs = people_qs.exclude(is_private=True)
        location_qs = location_qs.exclude(is_private=True)

    events = events_qs.select_related(
        'location', 'owner', 'start_date_source', 'end_date_source', 'location_source'
    ).prefetch_related(
        'timelines', 
        'additional_images',
        'description_sources',
        'tags',
        'attachments',
        'disputed_facts',
        'location__tags',
        'location__attachments',
        'location__description_sources',
        'location__established_date_source',
        'location__ceased_date_source',
        'location__owner',
        'location__aliases',
        'location__disputed_facts',
        'end_location__tags',
        'end_location__attachments',
        'end_location__description_sources',
        'end_location__aliases',
        'end_location__disputed_facts',
        models.Prefetch('people', queryset=people_qs.select_related(
            'birth_location', 'death_location',
            'birth_date_source', 'birth_location_source',
            'death_date_source', 'death_location_source'
        ).prefetch_related(
            'description_sources',
            'tags',
            'attachments',
            'disputed_facts',
            models.Prefetch('relationships_from', queryset=PersonRelationship.objects.all().select_related('to_person'))
        ))
    )
    
    # NEW LOGIC: Build base query components before filtering
    location_ids = request.GET.getlist('location')
    person_ids = request.GET.getlist('person')
    tag_ids = request.GET.getlist('tag')
    timeline_ids = request.GET.getlist('timeline')
    story_ids = request.GET.getlist('story')
    
    # --- PHASE 1: ADDITIVE BASE SCOPE ---
    if not timeline_ids:
        return TimelineEvent.objects.none()

    # 1.1 Base Timeline Scope
    all_timeline_ids = _get_expanded_timelines(timeline_ids)
    events = events.filter(timelines__id__in=all_timeline_ids).distinct()

    # 1.2 Auto-Events (Additive based on the people in Phase 1.1)
    show_births_deaths = request.GET.get('show_births_deaths')
    if show_births_deaths != 'false':
        # Get people who appear in the events of the selected timelines
        people_in_scope = Person.objects.filter(events__timelines__id__in=all_timeline_ids).distinct()
        
        auto_events = TimelineEvent.objects.filter(
            is_auto_generated=True,
            people__in=people_in_scope
        ).distinct()

        # Static guard against extreme outliers
        if events.exists():
            date_stats = events.aggregate(min_date=models.Min('start_date'))
            min_d = date_stats['min_date']
            if min_d:
                try:
                    cushion_date = min_d.replace(year=max(1, min_d.year - 200))
                    auto_events = auto_events.filter(start_date__gte=cushion_date)
                except (ValueError, OverflowError):
                    auto_events = auto_events.filter(start_date__year__gte=1000)
        else:
            auto_events = auto_events.filter(start_date__year__gte=1000)
            
        # Add auto-events to the base universe
        events = events | auto_events
    else:
        # User explicitly unchecked the box; purge any auto-events that might have been statically linked to the timeline in the database
        events = events.exclude(is_auto_generated=True)

    # --- PHASE 2: SUBTRACTIVE FILTERS (The Mask) ---
    
    # 2.1 Person Mask
    if person_ids:
        events = events.filter(people__id__in=person_ids).distinct()

    # 2.2 Location Mask
    if location_ids:
        expanded_location_ids = _get_expanded_locations(location_ids)
        events = events.filter(Q(location_id__in=expanded_location_ids) | Q(end_location_id__in=expanded_location_ids)).distinct()

    # 2.3 Tag Mask
    if tag_ids:
        events = events.filter(
            Q(tags__id__in=tag_ids) | 
            Q(location__tags__id__in=tag_ids) | 
            Q(people__tags__id__in=tag_ids)
        ).distinct()
    
    # 2.4 Story Mask (Subtractive: Only events in selected timelines AND this story)
    if story_ids:
        events = events.filter(storyevent__story_id__in=story_ids).distinct()

    # 2.5 Search Mask
    search_query = request.GET.get('search')
    if search_query:
        events = events.filter(
            Q(title__icontains=search_query) | 
            Q(description__icontains=search_query) |
            Q(location__aliases__name__icontains=search_query) |
            Q(end_location__aliases__name__icontains=search_query) |
            Q(people__name__icontains=search_query) |
            Q(people__birth_location__aliases__name__icontains=search_query) |
            Q(people__death_location__aliases__name__icontains=search_query)
        ).distinct()

    # 2.6 Date Mask
    start_filter = request.GET.get('start_date')
    end_filter = request.GET.get('end_date')

    if start_filter:
        events = events.filter(Q(start_date__gte=start_filter) | Q(end_date__gte=start_filter))
    
    if end_filter:
        events = events.filter(start_date__lte=end_filter)
        
    # 2.7 Certainty Mask
    certainty = request.GET.get('certainty')
    UNCERTAIN_PRECISIONS = ['circa', 'before', 'after', 'decade']
    if certainty == 'certain':
        events = events.exclude(start_date_precision__in=UNCERTAIN_PRECISIONS)
    elif certainty == 'uncertain':
        events = events.filter(start_date_precision__in=UNCERTAIN_PRECISIONS)

    return events.order_by('start_date', 'title')
@cache_page(60)  # Cache for 60 seconds
@vary_on_cookie
def events_json(request):
    """
    API endpoint to return events and related entities in JSON format.
    Uses serializers for modularity and performance.
    """
    events = _get_filtered_events(request)
    
    events_data = []
    all_locations = {}
    all_people = {}
    all_stories = {}
    sources_cache = {}
    conflict_tracker = {}

    # Build a single relationship cache for this entire request.
    # Structuring as two indexes (by from_person_id and to_person_id) gives
    # O(1) lookup in get_family_tree_data instead of a DB query per person.
    _all_rels = list(
        PersonRelationship.objects.all().select_related('from_person', 'to_person')
    )
    relationship_cache = {
        'from': defaultdict(list),
        'to': defaultdict(list),
    }
    for r in _all_rels:
        relationship_cache['from'][r.from_person_id].append(r)
        relationship_cache['to'][r.to_person_id].append(r)

    # Bulk-fetch StoryEvents upfront to avoid an N+1 query (one DB hit per event).
    story_events_by_event = defaultdict(list)
    for se in StoryEvent.objects.filter(event__in=events).select_related('story'):
        story_events_by_event[se.event_id].append(se)

    for event in events:
        # 1. Serialize core event data (includes nested tags, attachments, and simple people/location refs)
        item = serialize_event(event, sources_cache, request_user=request.user)

        # 2. Handle Story sequences (context-dependent sequence overrides)
        for se in story_events_by_event[event.id]:
            story = se.story
            item['stories'].append({
                'id': story.id,
                'title': story.title,
                'color': story.color,
                'sequence': se.sequence
            })
            if story.id not in all_stories:
                all_stories[story.id] = serialize_story(story, request_user=request.user)

        # 3. Conflict Detection & Entity Aggregation
        if event.location:
            key = (item['start'], item['end'], event.location.id)
            conflict_tracker[key] = conflict_tracker.get(key, 0) + 1
            if event.location.id not in all_locations:
                all_locations[event.location.id] = serialize_location(event.location, sources_cache, request_user=request.user)

        if event.end_location:
            if event.end_location.id not in all_locations:
                all_locations[event.end_location.id] = serialize_location(event.end_location, sources_cache, request_user=request.user)

        for p in event.people.all():
            if p.id not in all_people:
                all_people[p.id] = serialize_person(p, sources_cache, relationship_cache=relationship_cache, request_user=request.user)
        
        events_data.append(item)

    # 4. Collect Additional People (Relatives without events)
    # Ensure every person in a family tree or relationship list is included in the dictionary
    # so they are clickable and fully interactive in the UI.
    additional_ids = set()
    for p_id, p_data in list(all_people.items()):
        # Check relationships
        if 'relationships' in p_data:
            for rel in p_data['relationships']:
                if rel['to_person_id'] not in all_people:
                    additional_ids.add(rel['to_person_id'])
        # Check family tree nodes
        if 'family_tree' in p_data and p_data['family_tree']:
            for node in p_data['family_tree']['nodes']:
                if node['id'] not in all_people:
                    additional_ids.add(node['id'])

    if additional_ids:
        # Bulk load and serialize these additional people (relatives without direct events).
        for extra_p in Person.objects.filter(id__in=additional_ids):
            if extra_p.id not in all_people:
                all_people[extra_p.id] = serialize_person(
                    extra_p, sources_cache,
                    include_details=True,
                    relationship_cache=relationship_cache,
                    request_user=request.user
                )

    # 5. Return unified response
    # 5.1 Calculate Available Entities (Scoped ONLY by Timelines)
    # This matches the "Phase 1: Additive Base Scope" in _get_filtered_events.
    timeline_ids = request.GET.getlist('timeline')
    expanded_timeline_ids = _get_expanded_timelines(timeline_ids)
    
    # Base Scope Querset (Everything in the selected timelines)
    if expanded_timeline_ids:
        events_in_scope = TimelineEvent.objects.filter(timelines__id__in=expanded_timeline_ids)
    else:
        events_in_scope = TimelineEvent.objects.none()
    
    available_people = Person.objects.filter(events__in=events_in_scope).distinct().order_by('name')
    available_locations = Location.objects.filter(
        Q(events__in=events_in_scope) | Q(events_ending_here__in=events_in_scope)
    ).distinct().order_by('name')
    available_tags = Tag.objects.filter(
        Q(tagged_events__in=events_in_scope) |
        Q(locations__events__in=events_in_scope) |
        Q(people__events__in=events_in_scope) |
        Q(stories__storyevent__event__in=events_in_scope)
    ).distinct().order_by('name')

    # Sort stories by title (consistent with other entity sort keys)
    return JsonResponse({
        'events': events_data,
        'available_entities': {
            'people': [{'id': p.id, 'name': p.name} for p in available_people],
            'locations': [{'id': l.id, 'name': str(l)} for l in available_locations],
            'tags': [{'id': t.id, 'name': t.name} for t in available_tags]
        },
        'entities': {
            'locations': sorted(all_locations.values(), key=lambda x: x['name']),
            'people': sorted(all_people.values(), key=lambda x: x['name']),
            'stories': sorted(all_stories.values(), key=lambda x: x['title']),
            'sources': list(sources_cache.values())
        }
    })


class SourceTracker:
    """
    Accumulates and deduplicates source citations during Markdown generation,
    assigning sequential reference numbers for footnote/bibliography rendering.

    Usage::

        tracker = SourceTracker()
        text = f"Born{tracker.ref(person.birth_date_source)} in London."
        bibliography = tracker.bibliography()
    """

    def __init__(self):
        self._sources = []   # ordered list of Source objects in citation order
        self._index = {}     # source.id → 1-based reference number

    def ref(self, source_obj):
        """
        Returns a superscript HTML reference like ``<sup>[1]</sup>`` for a single
        source, or an empty string if ``source_obj`` is None.
        """
        if not source_obj:
            return ""
        if source_obj.id not in self._index:
            self._sources.append(source_obj)
            self._index[source_obj.id] = len(self._sources)
        return f" <sup>[{self._index[source_obj.id]}]</sup>"

    def multi_ref(self, source_objs):
        """
        Returns a combined superscript reference for an iterable of sources,
        e.g. ``<sup>[1, 3]</sup>``. Returns an empty string if no sources given.
        """
        indices = []
        for src in source_objs:
            if src.id not in self._index:
                self._sources.append(src)
                self._index[src.id] = len(self._sources)
            indices.append(str(self._index[src.id]))
        if not indices:
            return ""
        return f" <sup>[{', '.join(indices)}]</sup>"

    def bibliography(self):
        """Returns the ordered list of Source objects in first-citation order."""
        return self._sources


def export_markdown(request):
    """
    Generates a Markdown report of the filtered events, including people and
    stories appendices and a bibliography of cited sources.
    """
    events = _get_filtered_events(request)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md_content = f"# Timeline Report\n*Generated on {now}*\n\n---\n\n"

    tracker = SourceTracker()

    if not events.exists():
        md_content += "No events found matching the selected filters.\n"
    else:
        for event in events:
            date_label = format_date_with_precision(event.start_date, event.start_date_precision or 'exact', event.start_date_granularity or 'day')
            date_label += tracker.ref(event.start_date_source)
            if event.end_date:
                end_label = format_date_with_precision(event.end_date, event.end_date_precision or 'exact', event.end_date_granularity or 'day')
                end_label += tracker.ref(event.end_date_source)
                date_label += f" — {end_label}"

            md_content += f"## 📅 {date_label} | {event.title}\n"

            if event.location or event.end_location:
                loc_str = ""
                if event.location:
                    loc_str += f"{event.location}{tracker.ref(event.location_source)}"
                if event.end_location:
                    if loc_str:
                        loc_str += f" → {event.end_location}{tracker.ref(event.end_location_source)}"
                    else:
                        loc_str += f"To {event.end_location}{tracker.ref(event.end_location_source)}"
                md_content += f"**📍 Location:** {loc_str}\n\n"

            people = event.people.all()
            if people.exists():
                people_list = ", ".join([p.name for p in people])
                md_content += f"**👥 Involved:** {people_list}\n\n"

            stories = Story.objects.filter(storyevent__event=event)
            if stories.exists():
                stories_list = ", ".join([s.title for s in stories])
                md_content += f"**📖 Stories:** {stories_list}\n\n"

            desc_sources = tracker.multi_ref(event.description_sources.all())
            md_content += f"> {event.description}{desc_sources}\n\n"

            if event.link:
                md_content += f"[🔗 More Information]({event.link})\n"

            md_content += "\n---\n\n"

        # People Appendix
        all_people = Person.objects.filter(events__in=events).distinct().order_by('name')
        if all_people.exists():
            md_content += "# 👥 People Appendix\n\n"
            for person in all_people:
                name_display = person.name
                if person.disambiguation:
                    name_display += f" ({person.disambiguation})"

                md_content += f"## 👤 {name_display}\n"

                if person.gender != 'unknown':
                    md_content += f"**⚧ Gender:** {person.get_gender_display()}\n"

                birth_info = ""
                if person.birth_date:
                    date = format_date_with_precision(person.birth_date, person.birth_date_precision or 'exact', person.birth_date_granularity or 'day')
                    date += tracker.ref(person.birth_date_source)
                    loc_source = tracker.ref(person.birth_location_source)
                    loc = f" in {person.birth_location}{loc_source}" if person.birth_location else ""
                    birth_info = f"**👶 Birth:** {date}{loc}\n"

                death_info = ""
                if person.death_date:
                    date = format_date_with_precision(person.death_date, person.death_date_precision or 'exact', person.death_date_granularity or 'day')
                    date += tracker.ref(person.death_date_source)
                    loc_source = tracker.ref(person.death_location_source)
                    loc = f" in {person.death_location}{loc_source}" if person.death_location else ""
                    death_info = f"**⚰️ Death:** {date}{loc}\n"

                burial_info = ""
                if person.burial_location:
                    burial_info = f"**🪦 Burial:** {person.burial_location}{tracker.ref(person.burial_location_source)}\n"

                if birth_info or death_info or burial_info:
                    md_content += f"{birth_info}{death_info}{burial_info}\n"

                # Relationships
                rels = person.get_relationships()
                if rels:
                    rel_strings = []
                    for r in rels:
                        rel_str = f"{r['relationship_type'].title()}: {r['to_person'].name}"
                        rel_strings.append(rel_str)
                    md_content += f"**🔗 Relationships:** {', '.join(rel_strings)}\n\n"

                desc_sources = tracker.multi_ref(person.description_sources.all())
                if person.description:
                    md_content += f"> {person.description}{desc_sources}\n\n"

            md_content += "\n---\n\n"

        # Locations Appendix
        all_event_locations = Location.objects.filter(events__in=events).distinct()
        all_end_locations = Location.objects.filter(events_ending_here__in=events).distinct()
        all_birth_locations = Location.objects.filter(births__in=all_people).distinct()
        all_death_locations = Location.objects.filter(deaths__in=all_people).distinct()
        
        all_locations = (all_event_locations | all_end_locations | all_birth_locations | all_death_locations).distinct().order_by('name')

        if all_locations.exists():
            md_content += "# 📍 Locations Appendix\n\n"
            for loc in all_locations:
                md_content += f"## 🗺️ {loc.name}\n"
                
                meta_info = []
                if loc.established_date:
                    meta_info.append(f"Est: {format_date_with_precision(loc.established_date, loc.established_date_precision or 'exact')}{tracker.ref(loc.established_date_source)}")
                if loc.ceased_date:
                    meta_info.append(f"Ceased: {format_date_with_precision(loc.ceased_date, loc.ceased_date_precision or 'exact')}{tracker.ref(loc.ceased_date_source)}")
                if loc.coordinates:
                    meta_info.append(f"Coords: `{loc.coordinates}`{tracker.ref(loc.coordinates_source)}")
                
                if meta_info:
                    md_content += f"**Info:** {' | '.join(meta_info)}\n\n"

                if loc.description:
                    desc_sources = tracker.multi_ref(loc.description_sources.all())
                    md_content += f"> {loc.description}{desc_sources}\n\n"
            
            md_content += "\n---\n\n"

        # Stories Appendix
        all_stories = Story.objects.filter(storyevent__event__in=events).distinct().order_by('title')
        if all_stories.exists():
            md_content += "# 📖 Stories Appendix\n\n"
            for story in all_stories:
                md_content += f"## 📚 {story.title}\n"
                if story.color:
                    md_content += f"*Theme Color: {story.color}*\n\n"
                if story.description:
                    md_content += f"> {story.description}\n\n"

                story_events = StoryEvent.objects.filter(
                    story=story, event__in=events
                ).select_related('event').order_by('sequence', 'event__start_date')
                if story_events.exists():
                    md_content += "### Story Timeline:\n"
                    for se in story_events:
                        ev = se.event
                        date = format_date_with_precision(ev.start_date, ev.start_date_precision or 'exact', ev.start_date_granularity or 'day')
                        md_content += f"- **{date}**: {ev.title}\n"
                    md_content += "\n"

                md_content += "\n---\n\n"

        # Bibliography
        sources = tracker.bibliography()
        if sources:
            md_content += "# 📚 Bibliography\n\n"
            for idx, source in enumerate(sources, 1):
                md_content += f"{idx}. **{source.title}**"
                if source.parent:
                    md_content += f" (in *{source.parent.title}*)"
                if source.author:
                    md_content += f", by {source.author}"
                if source.publication_date:
                    md_content += f" ({source.publication_date})"
                if source.url:
                    md_content += f" - [Link]({source.url})"
                md_content += "\n"

    response = HttpResponse(md_content, content_type='text/markdown')
    filename = slugify(f"timeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}") + ".md"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response



def sources_library(request):
    """
    View to browse all Citation Sources and see what entities cite them.
    Aggregates usage manually since related_names are set to '+'
    """
    class SourceStat:
        def __init__(self, obj):
            self.obj = obj
            self.event_count = 0
            self.person_count = 0
            self.loc_count = 0
            self.usages = []
            self.total_usages = 0

    sources = list(Source.objects.all().order_by('title'))
    source_stats = {s.id: SourceStat(s) for s in sources}
    
    # Timeline Events
    events = TimelineEvent.objects.prefetch_related('description_sources').filter(
        models.Q(start_date_source__isnull=False) |
        models.Q(end_date_source__isnull=False) |
        models.Q(location_source__isnull=False) |
        models.Q(description_sources__isnull=False)
    ).distinct()
    
    for event in events:
        used_sources = set()
        if event.start_date_source_id: used_sources.add(event.start_date_source_id)
        if event.end_date_source_id: used_sources.add(event.end_date_source_id)
        if event.location_source_id: used_sources.add(event.location_source_id)
        for ds in event.description_sources.all():
            used_sources.add(ds.id)
            
        for sid in used_sources:
            if sid in source_stats:
                source_stats[sid].event_count += 1
                source_stats[sid].usages.append({'type': 'Event', 'title': event.title, 'id': event.id, 'link': f'/admin/timeline/timelineevent/{event.id}/change/'})
                
    # Persons
    people = Person.objects.prefetch_related('description_sources').filter(
        models.Q(birth_date_source__isnull=False) |
        models.Q(birth_location_source__isnull=False) |
        models.Q(death_date_source__isnull=False) |
        models.Q(death_location_source__isnull=False) |
        models.Q(description_sources__isnull=False)
    ).distinct()
    
    for person in people:
        used_sources = set()
        if person.birth_date_source_id: used_sources.add(person.birth_date_source_id)
        if person.birth_location_source_id: used_sources.add(person.birth_location_source_id)
        if person.death_date_source_id: used_sources.add(person.death_date_source_id)
        if person.death_location_source_id: used_sources.add(person.death_location_source_id)
        for ds in person.description_sources.all():
            used_sources.add(ds.id)
            
        for sid in used_sources:
            if sid in source_stats:
                source_stats[sid].person_count += 1
                source_stats[sid].usages.append({'type': 'Person', 'title': person.name, 'id': person.id, 'link': f'/admin/timeline/person/{person.id}/change/'})
                
    # Locations
    locations = Location.objects.prefetch_related('description_sources').filter(
        models.Q(coordinates_source__isnull=False) |
        models.Q(established_date_source__isnull=False) |
        models.Q(ceased_date_source__isnull=False) |
        models.Q(description_sources__isnull=False)
    ).distinct()
    
    for loc in locations:
        used_sources = set()
        if loc.coordinates_source_id: used_sources.add(loc.coordinates_source_id)
        if loc.established_date_source_id: used_sources.add(loc.established_date_source_id)
        if loc.ceased_date_source_id: used_sources.add(loc.ceased_date_source_id)
        for ds in loc.description_sources.all():
            used_sources.add(ds.id)
            
        for sid in used_sources:
            if sid in source_stats:
                source_stats[sid].loc_count += 1
                source_stats[sid].usages.append({'type': 'Location', 'title': loc.name, 'id': loc.id, 'link': f'/admin/timeline/location/{loc.id}/change/'})
                
    # Prepare list for template
    library_data = []
    for stat in source_stats.values():
        stat.total_usages = stat.event_count + stat.person_count + stat.loc_count
        stat.usages.sort(key=lambda x: x['title'])
        library_data.append(stat)
        
    library_data.sort(key=lambda x: str(x.obj))
    
    return render(request, 'timeline/sources.html', {'sources': library_data})

def get_history(request, model_name, obj_id):
    model_map = {'TimelineEvent': TimelineEvent, 'Person': Person, 'Location': Location}
    ModelClass = model_map.get(model_name)
    if not ModelClass:
        return JsonResponse({'error': 'Invalid model'}, status=400)
    
    obj = get_object_or_404(ModelClass, pk=obj_id)
    history_records = obj.history.all()
    
    history_data = []
    # simple_history orders by -history_date by default
    previous_record = None
    
    # We iterate from oldest to newest to compute diffs forwards
    for record in reversed(list(history_records)):
        changes = []
        if previous_record:
            diff = record.diff_against(previous_record)
            for change in diff.changes:
                changes.append({
                    'field': change.field,
                    'old': str(change.old),
                    'new': str(change.new)
                })
        else:
            changes.append({'field': 'All', 'old': '', 'new': 'Created'})
            
        history_data.append({
            'history_id': record.history_id,
            'date': record.history_date.isoformat(),
            'user': record.history_user.username if record.history_user else 'System',
            'type': record.get_history_type_display(),
            'changes': changes
        })
        previous_record = record
        
    # Reverse back so newest is first for the frontend
    history_data.reverse()
    return JsonResponse({'history': history_data})



def network_graph_api(request):
    """
    Returns the JSON representation of the entire active timeline
    for vis-network visualization, dynamically respecting user filters.
    """
    nodes = []
    edges = []

    events_qs = _get_filtered_events(request)
    
    person_ids = set()
    location_ids = set()
    source_ids = set()
    story_ids = set()

    # 1. Events
    for e in events_qs:
        events_node_id = f'event_{e.pk}'
        nodes.append({
            'id': events_node_id,
            'label': e.title,
            'shape': 'dot',
            'color': '#3B82F6', # Blue
            'group': 'event',
            'status': e.status,
            'title': f'Event Element (ID: {e.pk})'
        })
        
        if e.location:
            location_ids.add(e.location.pk)
            edges.append({'from': events_node_id, 'to': f'location_{e.location.pk}', 'label': 'occurred at'})
        
        for p in e.people.all():
            person_ids.add(p.pk)
            edges.append({'from': f'person_{p.pk}', 'to': events_node_id, 'label': 'participated in'})
            
        for src in e.description_sources.all():
            source_ids.add(src.pk)
            edges.append({'from': events_node_id, 'to': f'source_{src.pk}', 'label': 'desc sourced from'})
        if e.start_date_source:
             source_ids.add(e.start_date_source.pk)
             edges.append({'from': events_node_id, 'to': f'source_{e.start_date_source.pk}', 'label': 'start date sourced'})
        if e.end_date_source:
             source_ids.add(e.end_date_source.pk)
             edges.append({'from': events_node_id, 'to': f'source_{e.end_date_source.pk}', 'label': 'end date sourced'})
        if e.location_source:
             source_ids.add(e.location_source.pk)
             edges.append({'from': events_node_id, 'to': f'source_{e.location_source.pk}', 'label': 'location sourced'})

        for se in StoryEvent.objects.filter(event=e):
            story_ids.add(se.story_id)
            edges.append({'from': events_node_id, 'to': f'story_{se.story_id}', 'label': 'part of story'})

    # 2. People
    people = Person.objects.filter(pk__in=person_ids).prefetch_related('description_sources', 'relationships_from__to_person')
    for p in people:
        person_node_id = f'person_{p.pk}'
        nodes.append({
            'id': person_node_id,
            'label': p.name,
            'shape': 'icon',
            'icon': {'face': '"Font Awesome 6 Free"', 'code': '\uf007', 'weight': 900, 'color': '#10B981'}, # Green User
            'group': 'person',
            'status': p.status,
            'title': f'Person Entity (ID: {p.pk})'
        })
        
        if p.birth_location:
            location_ids.add(p.birth_location.pk)
            edges.append({'from': person_node_id, 'to': f'location_{p.birth_location.pk}', 'label': 'born at'})
        if p.death_location:
            location_ids.add(p.death_location.pk)
            edges.append({'from': person_node_id, 'to': f'location_{p.death_location.pk}', 'label': 'died at'})
            
        for src in p.description_sources.all():
             source_ids.add(src.pk)
             edges.append({'from': person_node_id, 'to': f'source_{src.pk}', 'label': 'desc sourced'})
             
        for rel in p.relationships_from.all():
            if rel.to_person.pk in person_ids:
                edges.append({'from': person_node_id, 'to': f'person_{rel.to_person.pk}', 'label': rel.get_relationship_type_display()})

    # 3. Locations
    locations = Location.objects.filter(pk__in=location_ids).select_related('parent').prefetch_related('description_sources')
    for loc in locations:
        loc_node_id = f'location_{loc.pk}'
        nodes.append({
            'id': loc_node_id,
            'label': loc.name,
            'shape': 'icon',
            'icon': {'face': '"Font Awesome 6 Free"', 'code': '\uf3c5', 'weight': 900, 'color': '#F59E0B'}, # Yellow Map Marker
            'group': 'location',
            'status': loc.status,
            'title': f'Location Node (ID: {loc.pk})'
        })
        
        if loc.parent:
            if loc.parent.pk in location_ids:
                edges.append({'from': loc_node_id, 'to': f'location_{loc.parent.pk}', 'label': 'part of'})
        
        for src in loc.description_sources.all():
             source_ids.add(src.pk)
             edges.append({'from': loc_node_id, 'to': f'source_{src.pk}', 'label': 'desc sourced'})

    # 4. Stories
    stories = Story.objects.filter(pk__in=story_ids).prefetch_related('tags')
    for s in stories:
        story_node_id = f'story_{s.pk}'
        nodes.append({
            'id': story_node_id,
            'label': s.title,
            'shape': 'icon',
            'icon': {'face': '"Font Awesome 6 Free"', 'code': '\uf02d', 'weight': 900, 'color': s.color or '#8B5CF6'}, # Purple Book
            'group': 'story',
            'title': f'Story Narrative (ID: {s.pk})'
        })
        
        for tag in s.tags.all():
            # Optional: link stories to tags if we want to show that in the graph
            pass

    # 4. Sources
    sources = Source.objects.filter(pk__in=source_ids).select_related('parent')
    for src in sources:
        src_node_id = f'source_{src.pk}'
        nodes.append({
            'id': src_node_id,
            'label': src.title,
            'shape': 'icon',
            'icon': {'face': '"Font Awesome 6 Free"', 'code': '\uf02d', 'weight': 900, 'color': '#6B7280'}, # Gray Book
            'group': 'source',
            'title': f'Citation Source (ID: {src.pk})'
        })
        
        if src.parent:
            if src.parent.pk in source_ids:
                edges.append({'from': src_node_id, 'to': f'source_{src.parent.pk}', 'label': 'contained in'})

    return JsonResponse({'nodes': nodes, 'edges': edges})

import json

@user_passes_test(lambda u: u.is_staff)
def backup_all_json(request):
    """
    Exports a high-fidelity 'Full Archive' including ALL events, people, locations,
    and private researcher notes. Staff only.
    """
    events = TimelineEvent.objects.all().select_related('owner', 'location', 'end_location')
    sources_cache = {}
    
    serialized_events = []
    
    # Bulk-fetch StoryEvents
    from collections import defaultdict
    story_events_by_event = defaultdict(list)
    for se in StoryEvent.objects.all().select_related('story'):
        story_events_by_event[se.event_id].append(se)

    for e in events:
        item = serialize_event(e, sources_cache=sources_cache, request_user=request.user, include_private=True)
        for se in story_events_by_event[e.id]:
            story = se.story
            item['stories'].append({
                'id': story.id,
                'title': story.title,
                'color': story.color,
                'sequence': se.sequence
            })
        serialized_events.append(item)
    
    # Also ensure we serialize ALL people and locations for a true backup
    entities = {
        'locations': [serialize_location(l, sources_cache, include_private=True) for l in Location.objects.all()],
        'people': [serialize_person(p, sources_cache, include_private=True) for p in Person.objects.all()],
        'stories': [serialize_story(s, request_user=request.user, include_private=True) for s in Story.objects.all()],
        'sources': list(sources_cache.values()),
    }

    export_payload = {
        'version': '3.0',
        'type': 'high-fidelity-backup',
        'export_date': datetime.now().isoformat(),
        'events': serialized_events,
        'entities': entities,
    }
    
    response = HttpResponse(json.dumps(export_payload, indent=2), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="timewrit_full_backup_{datetime.now().strftime("%Y%md_%H%M")}.json"'
    return response

def export_json(request):
    """
    Exports the filtered timeline events (Public only if logged out)
    for portability.
    """
    events = _get_filtered_events(request)
    sources_cache = {}
    
    serialized_events = []
    
    from collections import defaultdict
    story_events_by_event = defaultdict(list)
    for se in StoryEvent.objects.filter(event__in=events).select_related('story'):
        story_events_by_event[se.event_id].append(se)

    for e in events:
        # include_private=False ensuring public portability
        item = serialize_event(e, sources_cache=sources_cache, request_user=request.user, include_private=False)
        for se in story_events_by_event[e.id]:
            story = se.story
            item['stories'].append({
                'id': story.id,
                'title': story.title,
                'color': story.color,
                'sequence': se.sequence
            })
        serialized_events.append(item)
    
    export_payload = {
        'version': '2.0',
        'type': 'portable-export',
        'export_date': datetime.now().isoformat(),
        'events': serialized_events,
        'sources': list(sources_cache.values()),
    }
    
    response = HttpResponse(json.dumps(export_payload, indent=2), content_type='application/json')
    response['Content-Disposition'] = 'attachment; filename="timeline_portable.json"'
    return response

def export_gedcom(request):
    """
    Exports the People and their Relationships into a basic GEDCOM format.
    Ensures families (spouses/children) are correctly linked via FAM records.
    """
    from datetime import datetime
    from collections import defaultdict
    
    timeline_ids = request.GET.getlist('timeline')
    people_qs = Person.objects.filter(owner=request.user)
    if timeline_ids:
        people_qs = people_qs.filter(events__timelines__id__in=timeline_ids).distinct()
    
    # Internal maps for building FAM records
    # family_id -> {husb: id, wife: id, children: [ids]}
    families = {}
    next_fam_id = 1
    
    # person_id -> [family_ids where spouse]
    person_fams_s = defaultdict(list)
    # person_id -> family_id where child
    person_fam_c = {}
    
    people_ids = list(people_qs.values_list('id', flat=True))
    all_rels = PersonRelationship.objects.filter(
        models.Q(from_person_id__in=people_ids) | models.Q(to_person_id__in=people_ids)
    )
    
    # helper for finding/creating a family for a couple
    def get_couple_fam(h_id, w_id):
        nonlocal next_fam_id
        for fid, data in families.items():
            if (data['husb'] == h_id and data['wife'] == w_id) or \
               (data['husb'] == w_id and data['wife'] == h_id):
                return fid
        fid = next_fam_id
        next_fam_id += 1
        families[fid] = {'husb': h_id, 'wife': w_id, 'children': []}
        if h_id: person_fams_s[h_id].append(fid)
        if w_id: person_fams_s[w_id].append(fid)
        return fid

    # 1. Process Spouse relationships
    for rel in all_rels.filter(relationship_type='spouse'):
        get_couple_fam(rel.from_person_id, rel.to_person_id)
        
    # 2. Process Parent relationships
    # Group children by parents
    child_to_parents = defaultdict(set)
    for rel in all_rels.filter(relationship_type='parent'):
        child_to_parents[rel.to_person_id].add(rel.from_person_id)
        
    for c_id, parents in child_to_parents.items():
        parents = list(parents)
        if len(parents) >= 2:
            fid = get_couple_fam(parents[0], parents[1])
        elif len(parents) == 1:
            fid = get_couple_fam(parents[0], None)
        else:
            continue
        
        if c_id not in families[fid]['children']:
            families[fid]['children'].append(c_id)
        person_fam_c[c_id] = fid

    lines = []
    lines.append("0 HEAD")
    lines.append("1 SOUR TimeWrit")
    lines.append(f"1 DATE {datetime.now().strftime('%d %b %Y').upper()}")
    lines.append("1 GEDC")
    lines.append("2 VERS 5.5.1")
    lines.append("2 FORM LINEAGE_LINKED")
    lines.append("1 CHAR UTF-8")
    
    # INDI records
    for p in people_qs:
        lines.append(f"0 @I{p.id}@ INDI")
        # Name
        name_parts = p.name.split(' ')
        if len(name_parts) > 1:
            surname = name_parts[-1]
            given = " ".join(name_parts[:-1])
            lines.append(f"1 NAME {given} /{surname}/")
        else:
            lines.append(f"1 NAME {p.name}")
        
        # Gender mapping
        sex = 'U'
        if p.gender == 'male': sex = 'M'
        elif p.gender == 'female': sex = 'F'
        elif p.gender in ['non-binary', 'intersex']: sex = 'X'
        lines.append(f"1 SEX {sex}")
        if p.birth_date:
            lines.append("1 BIRT")
            lines.append(f"2 DATE {format_date_with_precision(p.birth_date, p.birth_date_precision or 'exact')}")
            if p.birth_location:
                lines.append(f"2 PLAC {p.birth_location.name}")
        if p.death_date:
            lines.append("1 DEAT")
            lines.append(f"2 DATE {format_date_with_precision(p.death_date, p.death_date_precision or 'exact')}")
            if p.death_location:
                lines.append(f"2 PLAC {p.death_location.name}")
        
        # Family pointers
        if p.id in person_fam_c:
            lines.append(f"1 FAMC @F{person_fam_c[p.id]}@")
        for fid in person_fams_s[p.id]:
            lines.append(f"1 FAMS @F{fid}@")
            
    # FAM records
    for fid, data in families.items():
        lines.append(f"0 @F{fid}@ FAM")
        if data['husb']:
            lines.append(f"1 HUSB @I{data['husb']}@")
        if data['wife']:
            lines.append(f"1 WIFE @I{data['wife']}@")
        for c_id in data['children']:
            lines.append(f"1 CHIL @I{c_id}@")
        
    lines.append("0 TRLR")
    
    response = HttpResponse("\n".join(lines), content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename="family_tree.ged"'
    return response

@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def submit_comment(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    # Honeypot check
    website = request.POST.get('website', '')
    if website:  # Bots usually fill this out
        return JsonResponse({'status': 'success'}, status=200)

    entity_type = request.POST.get('entity_type')
    entity_id = request.POST.get('entity_id')
    author_name = request.POST.get('author_name')
    if author_name:
        author_name = strip_tags(author_name)
    email = request.POST.get('email', '')
    body = request.POST.get('body')
    if body:
        body = strip_tags(body)

    if not all([entity_type, entity_id, author_name, body]):
        return JsonResponse({'error': 'Missing required fields'}, status=400)

    try:
        content_type = ContentType.objects.get(model=entity_type.lower())
        obj = content_type.get_object_for_this_type(pk=entity_id)

        PublicComment.objects.create(
            content_type=content_type,
            object_id=obj.pk,
            content_object=obj,
            author_name=author_name,
            email=email,
            body=body,
            # target_owner is auto-set in save()
        )
        return JsonResponse({'status': 'success'})

    except (ContentType.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Invalid entity'}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Entity not found'}, status=404)


class PDFReport(FPDF):
    def __init__(self, orientation='P', font_family='Serif', *args, **kwargs):
        super().__init__(orientation=orientation, *args, **kwargs)
        self.font_name = 'Times' if font_family == 'Serif' else 'Helvetica'
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()
        
    def header(self):
        # Premium feel: thin blue line at the top
        self.set_draw_color(59, 130, 246) # Blue-600
        self.set_line_width(0.5)
        self.line(10, 10, self.w - 10, 10)
        
        self.set_font(self.font_name, 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, 'TimeWrit Research Report', align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_name, 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)

    def chapter_title(self, title):
        self.set_font(self.font_name, 'B', 16)
        self.set_text_color(30, 41, 59) # Slate-800
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.set_font(self.font_name, '', 10) # Reset
        self.ln(5)

    def section_title(self, title):
        self.set_font(self.font_name, 'B', 12)
        self.set_text_color(51, 65, 85) # Slate-700
        # Explicitly reset X and use epw (effective page width)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 8, title, align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self.font_name, '', 10) # Immediate reset

    def body_text(self, text, indent=False):
        text = self.s(text)
        self.set_font(self.font_name, '', 10)
        self.set_text_color(71, 85, 105) # Slate-600
        self.set_x(self.l_margin)
        if indent:
            self.set_x(self.l_margin + 5)
            self.multi_cell(self.epw - 5, 5, text, markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            self.multi_cell(self.epw, 5, text, markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self.font_name, '', 10) # Explicit reset after markdown block
        self.ln(2)

    def s(self, text):
        """Sanitize text for Latin-1 encoding used by core PDF fonts."""
        if not text: return ""
        # Strip superscript tags for clean PDF output
        text = text.replace('<sup>', '').replace('</sup>', '')
        mapping = {
            '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
            '\u2014': '-', '\u2013': '-', '\u2026': '...', '\u00a0': ' ',
        }
        for char, repl in mapping.items():
            text = text.replace(char, repl)
        return text.encode('latin-1', 'replace').decode('latin-1')

def export_pdf(request):
    """
    Generates a professional PDF report using fpdf2, respecting filters and 
    user-selected configuration.
    """
    events = _get_filtered_events(request)
    
    # Configuration from request
    orientation = request.GET.get('orientation', 'P') # 'P' or 'L'
    font_family = request.GET.get('font_family', 'Serif')
    show_sections = request.GET.getlist('sections') # ['timeline', 'people', 'stories', 'bibliography']
    
    # If no sections selected via GET (e.g. direct link), default to all
    if not show_sections:
        show_sections = ['timeline', 'people', 'stories', 'bibliography']

    pdf = PDFReport(orientation=orientation, font_family=font_family)
    pdf.alias_nb_pages()
    
    # Title Page / Report Header
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.set_font(pdf.font_name, 'B', 24)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 20, 'Timeline Report', 0, 1, 'C')
    pdf.set_font(pdf.font_name, 'I', 10)
    pdf.cell(0, 10, f'Generated on {now}', 0, 1, 'C')
    pdf.ln(10)

    tracker = SourceTracker()
    base_right_margin = pdf.r_margin

    if 'timeline' in show_sections:
        pdf.chapter_title('Timeline Events')
        if not events.exists():
            pdf.body_text("No events found matching the selected filters.")
        else:
            for event in events:
                # Individual Event Block
                date_label = format_date_with_precision(event.start_date, event.start_date_precision or 'exact', event.start_date_granularity or 'day')
                date_label += tracker.ref(event.start_date_source)
                if event.end_date:
                    end_label = format_date_with_precision(event.end_date, event.end_date_precision or 'exact', event.end_date_granularity or 'day')
                    end_label += tracker.ref(event.end_date_source)
                    date_label += f" — {end_label}"
                
                # Check for image to determine layout
                has_image = bool(event.image)
                orig_margin = pdf.r_margin
                
                # Image Height Check: 34mm height (15% reduction)
                # Ensure we don't start it near the bottom
                if has_image and pdf.get_y() > pdf.h - 50:
                    pdf.add_page()
                
                start_y = pdf.get_y()
                start_page = pdf.page_no()
                
                # Ensure we start at the left margin to avoid carrying over X from previous event
                pdf.set_x(pdf.l_margin)
                
                if has_image:
                    pdf.set_right_margin(base_right_margin + 40) # Leave room for image (34mm + padding)

                # Header: Date | Title
                pdf.section_title(pdf.s(f"{date_label} | {event.title}"))
                
                # Metadata
                if event.location or event.end_location:
                    loc_str = ""
                    if event.location:
                        loc_str += f"{event.location}{tracker.ref(event.location_source)}"
                    if event.end_location:
                        if loc_str:
                            loc_str += f" -> {event.end_location}{tracker.ref(event.end_location_source)}"
                        else:
                            loc_str += f"To {event.end_location}{tracker.ref(event.end_location_source)}"
                    
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Location: {loc_str}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                people_involved = event.people.all()
                if people_involved.exists():
                    names = ", ".join([p.name for p in people_involved])
                    pdf.set_font(pdf.font_name, 'B', 9)
                    # Use explicit reset and width for safety
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Involved: {names}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                # Description
                desc_sources = tracker.multi_ref(event.description_sources.all())
                pdf.ln(2)
                pdf.body_text(f"{event.description}{desc_sources}", indent=True)
                
                # Place Image at the TOP of the block (aligned with title)
                if has_image:
                    try:
                        current_y = pdf.get_y()
                        current_page = pdf.page_no()
                        
                        # Go back to start page and pos to place image
                        if current_page == start_page:
                             pdf.image(event.image.path, x=pdf.w - 44, y=start_y, w=34)
                             # Ensure next content starts after the image OR the text, whichever is lower
                             # Add 5mm buffer
                             pdf.set_y(max(current_y, start_y + 34) + 5)
                        else:
                             # Page break happened; placing image at start_y might overlap old page content.
                             pdf.image(event.image.path, w=34)
                    except Exception:
                         pass
                    
                    # Reset margin explicitly
                    pdf.set_right_margin(base_right_margin)
                
                pdf.ln(5)

    if 'people' in show_sections:
        all_people = Person.objects.filter(events__in=events).distinct().order_by('name')
        if all_people.exists():
            pdf.add_page()
            pdf.chapter_title('People Appendix')
            for person in all_people:
                name_display = person.name
                if person.disambiguation:
                    name_display += f" ({person.disambiguation})"
                
                # Image layout check
                has_image = bool(person.image)
                orig_margin = pdf.r_margin
                
                if has_image and pdf.get_y() > pdf.h - 50:
                    pdf.add_page()
                
                start_y = pdf.get_y()
                start_page = pdf.page_no()
                
                # Ensure we start at the left margin to avoid carrying over X from previous person
                pdf.set_x(pdf.l_margin)

                if has_image:
                    pdf.set_right_margin(base_right_margin + 40)

                pdf.section_title(pdf.s(name_display))
                
                if person.gender != 'unknown':
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Gender: {person.get_gender_display()}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                # Life dates
                if person.birth_date:
                    date = format_date_with_precision(person.birth_date, person.birth_date_precision or 'exact', person.birth_date_granularity or 'day')
                    date += tracker.ref(person.birth_date_source)
                    loc_source = tracker.ref(person.birth_location_source)
                    loc = f" in {person.birth_location}{loc_source}" if person.birth_location else ""
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Birth: {date}{loc}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                if person.death_date:
                    date = format_date_with_precision(person.death_date, person.death_date_precision or 'exact', person.death_date_granularity or 'day')
                    date += tracker.ref(person.death_date_source)
                    loc_source = tracker.ref(person.death_location_source)
                    loc = f" in {person.death_location}{loc_source}" if person.death_location else ""
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Death: {date}{loc}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                if person.burial_location:
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Burial: {person.burial_location}{tracker.ref(person.burial_location_source)}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                # Relationships
                rels = person.get_relationships()
                if rels:
                    rel_strings = [f"{r['relationship_type'].title()}: {r['to_person'].name}" for r in rels]
                    pdf.set_font(pdf.font_name, 'B', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"Relationships: {', '.join(rel_strings)}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                if person.description:
                    desc_sources = tracker.multi_ref(person.description_sources.all())
                    pdf.ln(2)
                    pdf.body_text(f"{person.description}{desc_sources}", indent=True)
                
                # Place Image at the TOP
                if has_image:
                    try:
                        current_y = pdf.get_y()
                        current_page = pdf.page_no()
                        if current_page == start_page:
                            pdf.image(person.image.path, x=pdf.w - 44, y=start_y, w=34)
                            # Ensure next block starts after photo + padding
                            pdf.set_y(max(current_y, start_y + 34) + 5)
                        else:
                            pdf.image(person.image.path, x=pdf.w - 44, w=34)
                    except Exception:
                        pass
                    pdf.set_right_margin(base_right_margin)
                
                pdf.ln(5)
        
        # Location Appendix
        all_event_locations = Location.objects.filter(events__in=events).distinct()
        all_end_locations = Location.objects.filter(events_ending_here__in=events).distinct()
        all_birth_locations = Location.objects.filter(births__in=all_people).distinct()
        all_death_locations = Location.objects.filter(deaths__in=all_people).distinct()
        all_locations = (all_event_locations | all_end_locations | all_birth_locations | all_death_locations).distinct().order_by('name')

        if all_locations.exists():
            pdf.add_page()
            pdf.chapter_title('Locations Appendix')
            for loc in all_locations:
                pdf.section_title(pdf.s(loc.name))
                
                meta = []
                if loc.established_date:
                    meta.append(f"Est: {format_date_with_precision(loc.established_date, loc.established_date_precision or 'exact')}{tracker.ref(loc.established_date_source)}")
                if loc.ceased_date:
                    meta.append(f"Ceased: {format_date_with_precision(loc.ceased_date, loc.ceased_date_precision or 'exact')}{tracker.ref(loc.ceased_date_source)}")
                if loc.coordinates:
                    meta.append(f"Coords: {loc.coordinates}{tracker.ref(loc.coordinates_source)}")
                
                if meta:
                    pdf.set_font(pdf.font_name, 'I', 9)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(pdf.epw, 5, pdf.s(f"{' | '.join(meta)}"), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                if loc.description:
                    desc_sources = tracker.multi_ref(loc.description_sources.all())
                    pdf.ln(2)
                    pdf.body_text(f"{loc.description}{desc_sources}", indent=True)
                pdf.ln(5)

    if 'stories' in show_sections:
        all_stories = Story.objects.filter(storyevent__event__in=events).distinct().order_by('title')
        if all_stories.exists():
            pdf.add_page()
            pdf.chapter_title('Stories Appendix')
            for story in all_stories:
                pdf.section_title(pdf.s(story.title))
                if story.description:
                    pdf.body_text(story.description, indent=True)
                
                story_events = StoryEvent.objects.filter(
                    story=story, event__in=events
                ).select_related('event').order_by('sequence', 'event__start_date')
                
                if story_events.exists():
                    pdf.set_font(pdf.font_name, 'I', 9)
                    pdf.cell(0, 5, "Story Timeline:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    for se in story_events:
                        ev = se.event
                        date = format_date_with_precision(ev.start_date, ev.start_date_precision or 'exact', ev.start_date_granularity or 'day')
                        pdf.set_font(pdf.font_name, '', 9)
                        pdf.set_x(pdf.get_x() + 5) # Indent
                        pdf.write(5, pdf.s(f"- {date}: {ev.title}\n"))
                        pdf.set_x(pdf.get_x() - 5) # Revert indent for next line if needed
                pdf.ln(8)

    if 'bibliography' in show_sections:
        sources = tracker.bibliography()
        if sources:
            pdf.add_page()
            pdf.chapter_title('Bibliography')
            for idx, source in enumerate(sources, 1):
                pdf.set_font(pdf.font_name, 'B', 10)
                pdf.set_x(pdf.l_margin)
                
                details = []
                if source.parent: details.append(f"in {source.parent.title}")
                if source.author: details.append(f"by {source.author}")
                if source.publication_date: details.append(f"({source.publication_date})")
                
                source_text = f"{idx}. {source.title}"
                if details:
                    source_text += f" ({', '.join(details)})"
                
                pdf.multi_cell(pdf.epw, 6, pdf.s(source_text), markdown=False, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                if source.url:
                    pdf.ln(5)
                    pdf.set_font(pdf.font_name, '', 8)
                    pdf.set_text_color(59, 130, 246)
                    pdf.set_x(pdf.get_x() + 5) # Indent
                    pdf.write(5, pdf.s(f"Link: {source.url}"))
                    pdf.set_text_color(71, 85, 105)
                pdf.ln(8)

    # Output to response
    filename = slugify(f"timeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}") + ".pdf"
    
    # Use BytesIO to avoid any encoding corruption during transmission
    buffer = io.BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    
    return FileResponse(buffer, as_attachment=True, filename=filename)

def global_search_json(request):
    """
    Returns search results across all major entity types in a categorized JSON format.
    Publicly accessible to support the Wikipedia-style frontend.
    """
    query = request.GET.get('q', '').strip()
    if not query or len(query) < 2:
        return JsonResponse({'results': {}})

    results = {
        'events': [],
        'people': [],
        'locations': [],
        'sources': [],
        'stories': [],
        'attachments': []
    }

    # Helper to check privacy
    is_public = not request.user.is_authenticated


    # 1. Events - Deduplicate by Title alone to handle varied dates for same event
    events_qs = TimelineEvent.objects.filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    )
    if is_public:
        events_qs = events_qs.exclude(is_private=True)
    events_qs = events_qs.distinct().order_by('title', '-start_date')
    
    seen_event_titles = set()
    for e in events_qs:
        key = e.title.strip().lower()
        if key not in seen_event_titles:
            results['events'].append({'id': e.id, 'title': e.title, 'date': str(e.start_date)})
            seen_event_titles.add(key)
            if len(results['events']) >= 10: break

    # 2. People - Deduplicate by Name
    people_qs = Person.objects.filter(
        Q(name__icontains=query) | Q(disambiguation__icontains=query)
    )
    if is_public:
        people_qs = people_qs.exclude(is_private=True)
    people_qs = people_qs.distinct().order_by('name')
    seen_people = set()
    for p in people_qs:
        key = p.name.strip().lower()
        if key not in seen_people:
            results['people'].append({'id': p.id, 'name': p.name, 'disambiguation': p.disambiguation})
            seen_people.add(key)
            if len(results['people']) >= 10: break

    # 3. Locations - Deduplicate by Name
    locations_qs = Location.objects.filter(
        Q(name__icontains=query) | Q(aliases__name__icontains=query)
    )
    if is_public:
        locations_qs = locations_qs.exclude(is_private=True)
    locations_qs = locations_qs.distinct().order_by('name')
    seen_locations = set()
    for l in locations_qs:
        key = l.name.strip().lower()
        if key not in seen_locations:
            results['locations'].append({'id': l.id, 'name': l.name})
            seen_locations.add(key)
            if len(results['locations']) >= 10: break

    # 4. Sources - Deduplicate by Title
    sources_qs = Source.objects.filter(
        Q(title__icontains=query) | Q(author__icontains=query)
    ).distinct().order_by('title')
    seen_sources = set()
    for s in sources_qs:
        key = s.title.strip().lower()
        if key not in seen_sources:
            results['sources'].append({'id': s.id, 'title': s.title, 'author': s.author})
            seen_sources.add(key)
            if len(results['sources']) >= 10: break

    # 5. Stories - Deduplicate by Title
    stories_qs = Story.objects.filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    )
    if is_public:
        stories_qs = stories_qs.exclude(is_private=True)
    stories_qs = stories_qs.distinct().order_by('title')
    seen_stories = set()
    for st in stories_qs:
        key = st.title.strip().lower()
        if key not in seen_stories:
            results['stories'].append({'id': st.id, 'title': st.title})
            seen_stories.add(key)
            if len(results['stories']) >= 10: break

    # 6. Attachments - Deduplicate by Title
    attachments_qs = Attachment.objects.filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    ).distinct().order_by('title')
    seen_attachments = set()
    for a in attachments_qs:
        key = a.title.strip().lower()
        if key not in seen_attachments:
            results['attachments'].append({'id': a.id, 'title': a.title, 'type': a.file_type})
            seen_attachments.add(key)
            if len(results['attachments']) >= 10: break

    return JsonResponse({'results': results})
