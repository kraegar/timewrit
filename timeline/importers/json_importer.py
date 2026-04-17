import json
import io
from typing import List, Dict, Any, Tuple
from ..models import (
    TimelineEvent, Location, Person, Tag, Story, StoryEvent, 
    Timeline, Source, PersonRelationship, LocationAlias, 
    Attachment, EventImage, DisputedFact, PublicComment, ResearchQuestion
)
from django.utils.dateparse import parse_date
from django.contrib.contenttypes.models import ContentType

class JsonEventImporter:
    """
    Advanced Multi-Stage Importer for Timewrit Deep Archives (v4.0).
    Ensures structural integrity by processing hierarchical and linked entities
    in dependency order before events.
    """
    def __init__(self, user=None):
        self.user = user
        from collections import defaultdict
        self.stats = defaultdict(int)

    def parse(self, file_obj) -> Dict[str, Any]:
        if isinstance(file_obj, bytes):
            content = file_obj.decode('utf-8')
        elif hasattr(file_obj, 'read'):
            content = file_obj.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8')
        else:
            content = file_obj
        return json.loads(content)

    def import_data(self, file_obj) -> Tuple[int, List[str]]:
        parsed_data = self.parse(file_obj)
        errors = []
        created_count = 0

        # Detection logic
        is_deep_archive = False
        if isinstance(parsed_data, dict):
            if parsed_data.get('type') == 'deep-archive' or parsed_data.get('version') == '4.0':
                is_deep_archive = True
        
        if not is_deep_archive:
            # Fallback to legacy event-centric import
            return self._legacy_import(parsed_data)

        entities = parsed_data.get('entities', {})
        
        try:
            # 1. Base Entities (No FK dependencies)
            self._import_tags(entities.get('tags', []))
            self._import_sources(entities.get('sources', []))
            
            # 2. Hierarchical Infrastructure (Parent links)
            self._import_locations(entities.get('locations', []))
            self._import_timelines(entities.get('timelines', []))
            
            # 3. People & Stories
            self._import_people(entities.get('people', []))
            self._import_stories(entities.get('stories', []))
            
            # 4. Connecting People (Relationships)
            self._import_relationships(entities.get('relationships', []))
            
            # 5. Events (The Final Graph)
            created_count, event_errors = self._import_events(entities.get('events', []))
            errors.extend(event_errors)

            # 6. Generic Relations (Disputed Facts, Research Questions, etc.)
            self._import_generic_relations(entities)
            
            
        except Exception as e:
            errors.append(f"Critical error during deep import: {str(e)}")

        summary = ", ".join([f"{count} {key.capitalize()}" for key, count in self.stats.items()])
        return self.stats.get('events', 0), errors if errors else [f"Imported: {summary}"]

    def _import_tags(self, tags: List[Dict]):
        for t in tags:
            tag, created = Tag.objects.update_or_create(
                name=t['name'],
                defaults={
                    'color': t.get('color', '#3B82F6'),
                    'researcher_notes': t.get('researcher_notes', ''),
                    'needs_research': t.get('needs_research', False)
                }
            )
            self.stats['tags'] += 1

    def _import_sources(self, sources: List[Dict]):
        created = {}
        for s_data in sources:
            source, _ = Source.objects.update_or_create(
                title=s_data['title'],
                # Secondary selector: author or date if available to help disambiguate
                defaults={
                    'author': s_data.get('author', ''),
                    'publication_date': s_data.get('publication_date'),
                    'url': s_data.get('url'),
                    'researcher_notes': s_data.get('researcher_notes', ''),
                    'needs_research': s_data.get('needs_research', False),
                    'is_private': s_data.get('is_private', False),
                    'owner': self.user
                }
            )
            created[s_data['title']] = source
            self.stats['sources'] += 1
        
        # Resolve parents
        for s_data in sources:
            if s_data.get('parent_title'):
                parent = created.get(s_data['parent_title'])
                if parent:
                    Source.objects.filter(pk=created[s_data['title']].pk).update(parent=parent)

    def _import_locations(self, locations: List[Dict]):
        # Recursive-style parent resolution
        created = {}
        
        def _get_or_create_loc(loc_data):
            name = loc_data['name']
            if name in created:
                return created[name]
            
            parent = None
            if loc_data.get('parent_name'):
                # Find parent data in the full list
                parent_data = next((l for l in locations if l['name'] == loc_data['parent_name']), None)
                if parent_data:
                    parent = _get_or_create_loc(parent_data)
            
            loc, _ = Location.objects.update_or_create(
                name=name,
                parent=parent,
                defaults={
                    'coordinates': loc_data.get('coordinates'),
                    'description': loc_data.get('description', ''),
                    'image': loc_data.get('image_path') or loc_data.get('image'),
                    'link': loc_data.get('link'),
                    'established_date': parse_date(loc_data['established_date']) if loc_data.get('established_date') else None,
                    'established_date_precision': loc_data.get('established_date_precision', 'exact'),
                    'established_date_granularity': loc_data.get('established_date_granularity', 'day'),
                    'ceased_date': parse_date(loc_data['ceased_date']) if loc_data.get('ceased_date') else None,
                    'ceased_date_precision': loc_data.get('ceased_date_precision', 'exact'),
                    'ceased_date_granularity': loc_data.get('ceased_date_granularity', 'day'),
                    'status': loc_data.get('status', 'unverified'),
                    'researcher_notes': loc_data.get('researcher_notes', ''),
                    'needs_research': loc_data.get('needs_research', False),
                    'is_private': loc_data.get('is_private', False),
                    'owner': self.user
                }
            )
            self.stats['locations'] += 1
            
            # Import Aliases
            for alias_data in loc_data.get('aliases', []):
                LocationAlias.objects.get_or_create(
                    location=loc,
                    name=alias_data['name'],
                    defaults={
                        'valid_from': parse_date(alias_data['valid_from']) if alias_data.get('valid_from') else None,
                        'valid_to': parse_date(alias_data['valid_to']) if alias_data.get('valid_to') else None,
                    }
                )
            
            created[name] = loc
            return loc

        for l in locations:
            _get_or_create_loc(l)

    def _import_timelines(self, timelines: List[Dict]):
        created = {}
        def _get_or_create_tl(tl_data):
            name = tl_data['name']
            if name in created: return created[name]
            parent_obj = None
            if tl_data.get('parent_name'):
                p_data = next((t for t in timelines if t['name'] == tl_data['parent_name']), None)
                if p_data: parent_obj = _get_or_create_tl(p_data)
            
            tl, _ = Timeline.objects.update_or_create(
                name=name,
                defaults={
                    'parent': parent_obj,
                    'description': tl_data.get('description', ''),
                    'is_default': tl_data.get('is_default', False),
                    'researcher_notes': tl_data.get('researcher_notes', ''),
                    'needs_research': tl_data.get('needs_research', False),
                    'is_private': tl_data.get('is_private', False),
                    'owner': self.user
                }
            )
            created[name] = tl
            self.stats['timelines'] += 1
            return tl
        for t in timelines: _get_or_create_tl(t)

    def _import_people(self, people: List[Dict]):
        for p in people:
            person, _ = Person.objects.update_or_create(
                name=p['name'],
                disambiguation=p.get('disambiguation'),
                defaults={
                    'gender': p.get('gender', 'unknown'),
                    'gender_custom': p.get('gender_custom'),
                    'status': p.get('status', 'unverified'),
                    'description': p.get('description', ''),
                    'image': p.get('image_path') or p.get('image'),
                    'link': p.get('link'),
                    'birth_date': parse_date(p['birth_date']) if p.get('birth_date') else None,
                    'birth_date_precision': p.get('birth_date_precision', 'exact'),
                    'birth_date_granularity': p.get('birth_date_granularity', 'day'),
                    'death_date': parse_date(p['death_date']) if p.get('death_date') else None,
                    'death_date_precision': p.get('death_date_precision', 'exact'),
                    'death_date_granularity': p.get('death_date_granularity', 'day'),
                    'burial_location': p.get('burial_location'),
                    'researcher_notes': p.get('researcher_notes', ''),
                    'needs_research': p.get('needs_research', False),
                    'is_private': p.get('is_private', False),
                    'owner': self.user
                }
            )
            self.stats['people'] += 1

    def _import_stories(self, stories: List[Dict]):
        for s in stories:
            Story.objects.update_or_create(
                title=s.get('title') or s.get('story_title'),
                defaults={
                    'description': s.get('description', ''),
                    'color': s.get('color', '#8B5CF6'),
                    'researcher_notes': s.get('researcher_notes', ''),
                    'needs_research': s.get('needs_research', False),
                    'is_private': s.get('is_private', False),
                    'owner': self.user
                }
            )
            self.stats['stories'] += 1

    def _import_relationships(self, rels: List[Dict]):
        for r in rels:
            from_p = Person.objects.filter(name=r['from_person_name']).first()
            to_p = Person.objects.filter(name=r['to_person_name']).first()
            if from_p and to_p:
                PersonRelationship.objects.update_or_create(
                    from_person=from_p,
                    to_person=to_p,
                    relationship_type=r.get('type') or r.get('relationship_type'),
                    defaults={
                        'start_date': parse_date(r['start_date']) if r.get('start_date') else None,
                        'end_date': parse_date(r['end_date']) if r.get('end_date') else None,
                        'notes': r.get('notes', ''),
                    }
                )
                self.stats['relationships'] += 1

    def _import_events(self, events: List[Dict]) -> Tuple[int, List[str]]:
        count = 0
        errors = []
        for e in events:
            try:
                # Resolve primary FKs
                location = Location.objects.filter(name=e.get('location_name')).first() if e.get('location_name') else None
                end_loc = Location.objects.filter(name=e.get('end_location_name')).first() if e.get('end_location_name') else None
                
                # Use 'event_title' if available to avoid mangled tooltip 'title'
                canonical_title = e.get('event_title') or e.get('title')
                
                event, created = TimelineEvent.objects.update_or_create(
                    title=canonical_title,
                    start_date=parse_date(e['start_date']),
                    owner=self.user,
                    defaults={
                        'description': e.get('description', ''),
                        'end_date': parse_date(e['end_date']) if e.get('end_date') else None,
                        'start_date_precision': e.get('start_date_precision', 'exact'),
                        'start_date_granularity': e.get('start_date_granularity', 'day'),
                        'end_date_precision': e.get('end_date_precision', 'exact'),
                        'end_date_granularity': e.get('end_date_granularity', 'day'),
                        'location': location,
                        'end_location': end_loc,
                        'status': e.get('status', 'unverified'),
                        'is_private': e.get('is_private', False),
                        'is_auto_generated': e.get('is_auto_generated', False),
                        'researcher_notes': e.get('researcher_notes', ''),
                        'needs_research': e.get('needs_research', False),
                        'link': e.get('link'),
                        'image': e.get('image_path') or e.get('image')
                    }
                )
                
                # Resolve M2Ms
                if e.get('people'):
                    event.people.set(Person.objects.filter(name__in=e['people']))
                if e.get('timelines'):
                    event.timelines.set(Timeline.objects.filter(name__in=e['timelines']))
                if e.get('tags'):
                    event.tags.set(Tag.objects.filter(name__in=[t['name'] for t in e['tags']]))

                # Story links
                for s_link in e.get('stories', []):
                    story = Story.objects.filter(title=s_link['title']).first()
                    if story:
                        StoryEvent.objects.get_or_create(story=story, event=event, defaults={'sequence': s_link.get('sequence', 0)})

                # Attachments & Gallery
                self._import_attachments(event, e.get('attachments', []), 'event')
                for img in e.get('images', []):
                    if img.get('path'):
                        EventImage.objects.get_or_create(event=event, image=img['path'], defaults={'caption': img.get('caption', '')})

                count += 1
            except Exception as ex:
                errors.append(f"Event import error '{e.get('title')}': {str(ex)}")
        return count, errors

    def _import_attachments(self, obj, attachments: List[Dict], type_name: str):
        for a in attachments:
            path = a.get('relative_path') or a.get('url')
            if path:
                attachment, _ = Attachment.objects.update_or_create(
                    file=path,
                    defaults={
                        'title': a.get('title', 'Imported'),
                        'file_type': a.get('type', 'other'),
                        'description': a.get('description', ''),
                        'owner': self.user
                    }
                )
                self.stats['attachments'] += 1
                if type_name == 'event': attachment.events.add(obj)

    def _import_generic_relations(self, entities: Dict):
        """
        Processes Disputed Facts, Research Questions, and Public Comments 
        nested within their parent entities.
        """
        # We need to map model names to their actual classes for ContentType resolution
        model_map = {
            'location': Location,
            'person': Person,
            'event': TimelineEvent,
            'story': Story,
        }

        for type_key, model_class in model_map.items():
            entity_list = entities.get(f"{type_key}s", [])
            for e_data in entity_list:
                # Find the existing object by natural key
                name_key = 'title' if type_key in ['event', 'story'] else 'name'
                obj = model_class.objects.filter(**{name_key: e_data[name_key]}).first()
                if not obj: continue

                ct = ContentType.objects.get_for_model(model_class)

                # Disputed Facts
                for df in e_data.get('disputed_facts', []):
                    if isinstance(df, dict):
                        for field, choices in df.items():
                            for choice in choices:
                                DisputedFact.objects.update_or_create(
                                    content_type=ct, object_id=obj.id,
                                    field_name=field,
                                    alternative_value=choice['alternative_value'],
                                    defaults={
                                        'notes': choice.get('notes', ''), 
                                        'is_resolved': choice.get('is_resolved', False),
                                        'owner': self.user
                                    }
                                )
                                self.stats['disputed_facts'] += 1

                # Public Comments
                for pc in e_data.get('public_comments', []):
                    PublicComment.objects.update_or_create(
                        content_type=ct, object_id=obj.id,
                        author_name=pc['author_name'],
                        body=pc['body'],
                        defaults={
                            'status': 'approved', 
                            'created_at': parse_date(pc['created_at']) if pc.get('created_at') else None,
                            'target_owner': self.user # Take over target ownership for notifications
                        }
                    )
                    self.stats['public_comments'] += 1

                # Research Questions
                for rq in e_data.get('research_questions', []):
                    ResearchQuestion.objects.update_or_create(
                        content_type=ct, object_id=obj.id,
                        question=rq['question'],
                        defaults={
                            'answer': rq.get('answer'), 
                            'status': rq.get('status', 'open'),
                            'owner': self.user
                        }
                    )
                    self.stats['research_questions'] += 1

    def _legacy_import(self, data):
        # [Implementation of old create_record logic redirected here if needed]
        # For now, we recommend current v4.0 for best results.
        return 0, ["Legacy import format detected. Please use v4.0 Deep Archive for full data restoration."]
