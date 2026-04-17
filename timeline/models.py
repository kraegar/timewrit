from django.db import models
from django.contrib.auth.models import User
from simple_history.models import HistoricalRecords
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
import datetime
import re


MARKDOWN_HELP_TEXT = mark_safe("""
<details style="margin-top: 0.5rem; border: 1px solid #e5e7eb; padding: 0.75rem; border-radius: 0.375rem; background-color: #f9fafb; font-size: 0.875rem;">
    <summary style="cursor: pointer; font-weight: 600; color: #2563eb;">Markdown formatting is supported. Click here for a cheat sheet.</summary>
    <div style="margin-top: 0.75rem; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; color: #374151; line-height: 1.5;"># Heading 1
## Heading 2
**Bold Text**
*Italic Text*
- Bulleted item 1
- Bulleted item 2
1. Numbered item 1
2. Numbered item 2
[Link description](https://example.com)
> Block quote text</div>
</details>
""")

GENDER_CHOICES = [
    ('male', 'Male'),
    ('female', 'Female'),
    ('non-binary', 'Non-binary'),
    ('intersex', 'Intersex'),
    ('other', 'Other'),
    ('unknown', 'Unknown'),
]

# ---------------------------------------------------------------------------
# Date precision and granularity
# ---------------------------------------------------------------------------

DATE_PRECISION_CHOICES = [
    ('exact',  'Exact'),
    ('circa',  'Circa (c.)'),
    ('before', 'Before (bef.)'),
    ('after',  'After (aft.)'),
    ('decade', 'Decade (e.g. 1840s)'),
]

DATE_GRANULARITY_CHOICES = [
    ('day',   'Day  (June 1, 1847)'),
    ('month', 'Month  (June 1847)'),
    ('year',  'Year  (1847)'),
]




def _fmt_date(date, granularity, bce_year=None):
    """
    Formats a ``datetime.date`` to a string at the requested granularity.

    Args:
        date:        A ``datetime.date`` instance.
        granularity: One of ``DATE_GRANULARITY_CHOICES`` values.
        bce_year:    If provided, use this integer as the year label (BCE display).

    Returns:
        e.g. ``"June 1, 1847"`` (day), ``"June 1847"`` (month), ``"1847"`` (year).
    """
    year_label = str(bce_year) if bce_year is not None else str(date.year)
    if granularity == 'year':
        return year_label
    if granularity == 'month':
        month_name = date.strftime('%B')
        return f'{month_name} {year_label}'
    # Default: day-level — avoid %-d (POSIX-only) by interpolating day directly
    day = str(date.day)
    month_name = date.strftime('%B')
    return f'{month_name} {day}, {year_label}'


def format_date_with_precision(date, precision, granularity='day'):
    """
    Returns a human-readable date string combining precision (certainty) and
    granularity (resolution).

    Args:
        date:        A ``datetime.date`` instance, or ``None``.
        precision:   One of ``DATE_PRECISION_CHOICES`` values.
        granularity: One of ``DATE_GRANULARITY_CHOICES`` values (default ``'day'``).

    Returns:
        Examples: ``"c. 1847"`` (circa+year), ``"1840s"`` (decade),
        ``"June 1, 1847"`` (exact+day).  Returns an empty string when
        ``date`` is ``None``.
    """
    if not date:
        return ''

    if precision == 'decade':
        decade = (date.year // 10) * 10
        return f'{decade}s'
    base = _fmt_date(date, granularity)
    if precision == 'circa':
        return f'c. {base}'
    if precision == 'before':
        return f'bef. {base}'
    if precision == 'after':
        return f'aft. {base}'
    # exact
    return base


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=50, default="#3B82F6", help_text="Hex color code (e.g. #3B82F6) or Tailwind color class")
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    
    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class Source(models.Model):
    title = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children', help_text="Optional parent source (e.g. the book this page is in)")
    url = models.URLField(blank=True, null=True, help_text="Link to the source online")
    author = models.CharField(max_length=255, blank=True, null=True)
    publication_date = models.CharField(max_length=255, blank=True, null=True)
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sources', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='sources')
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")

    def __str__(self):
        if self.parent:
            return f"{self.parent} - {self.title}"
        if self.author:
            return f"{self.title} by {self.author}"
        return self.title

    class Meta:
        ordering = ['title']

STATUS_CHOICES = [
    ('verified', 'Verified'),
    ('unverified', 'Unverified'),
    ('estimate', 'Rough Estimate'),
    ('disputed', 'Disputed'),
]

class Location(models.Model):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    # Storing coordinates as a simple string "lat,long" for now, or JSON if we want more structure.
    coordinates = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. '31.7126,-110.0676'")
    coordinates_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    description = models.TextField(blank=True, null=True, help_text=MARKDOWN_HELP_TEXT)
    description_sources = models.ManyToManyField('Source', blank=True, related_name='+')
    image = models.ImageField(upload_to='location_images/', blank=True, null=True)
    link = models.URLField(blank=True, null=True, help_text="Optional external link")
    established_date = models.DateField(blank=True, null=True, help_text="When this location was founded or built")
    established_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    established_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    established_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ceased_date = models.DateField(blank=True, null=True, help_text="When this location ceased to exist or was destroyed")
    ceased_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    ceased_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    ceased_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unverified', db_index=True)
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='locations', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='locations')
    
    disputed_facts = GenericRelation('DisputedFact')
    public_comments = GenericRelation('PublicComment')
    research_questions = GenericRelation('ResearchQuestion')
    history = HistoricalRecords(excluded_fields=['updated_at'])
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")

    def __str__(self):
        if self.parent:
            return f"{self.parent} > {self.name}"
        return self.name

    class Meta:
        ordering = ['name']

class LocationAlias(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='aliases')
    name = models.CharField(max_length=255)
    valid_from = models.DateField(blank=True, null=True, help_text="Start date for this alias (inclusive)")
    valid_to = models.DateField(blank=True, null=True, help_text="End date for this alias (inclusive)")
    
    def __str__(self):
        return f"{self.name} (Alias for {self.location.name})"
    
    class Meta:
        ordering = ['valid_from', 'name']
        verbose_name_plural = 'Location Aliases'

class Person(models.Model):
    name = models.CharField(max_length=255)
    disambiguation = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. 'The Younger' or 'Farmer' to distinguish from others with the same name")
    description = models.TextField(blank=True, null=True, help_text=MARKDOWN_HELP_TEXT)
    description_sources = models.ManyToManyField('Source', blank=True, related_name='+')
    image = models.ImageField(upload_to='person_images/', blank=True, null=True)
    link = models.URLField(blank=True, null=True, help_text="Optional external link")
    birth_date = models.DateField(blank=True, null=True)
    birth_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    birth_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    birth_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    birth_location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='births')
    birth_location_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    death_date = models.DateField(blank=True, null=True)
    death_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    death_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    death_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    death_location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='deaths')
    death_location_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    burial_location = models.CharField(max_length=255, blank=True, null=True, help_text="Free-form text for burial site (e.g. 'Boot Hill Cemetery, Tombstone, AZ')")
    burial_location_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, default='unknown', blank=True, null=True)
    gender_custom = models.CharField(max_length=100, blank=True, null=True, help_text="Specific gender identity if 'Other' is selected")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unverified', db_index=True)
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='people', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='people')
    
    disputed_facts = GenericRelation('DisputedFact')
    public_comments = GenericRelation('PublicComment')
    research_questions = GenericRelation('ResearchQuestion')
    history = HistoricalRecords(excluded_fields=['updated_at'])
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        if self.image:
            logger.info(f"🔍 DEBUG: Saving Person '{self.name}' with image '{self.image.name}'")
            try:
                logger.info(f"   - Storage: {self.image.storage.__class__.__name__}")
                if hasattr(self.image.storage, 'bucket_name'):
                    logger.info(f"   - Bucket: {self.image.storage.bucket_name}")
            except Exception as e:
                logger.error(f"   - Storage Debug Error: {e}")
        else:
            logger.info(f"🔍 DEBUG: Saving Person '{self.name}' with NO IMAGE")

        super().save(*args, **kwargs)
        
        # Handle Birth Event
        if self.birth_date or self.birth_location:
            birth_title = f"Birth of {self.name}"
            # Find by people link + auto-flag + title keywords to be robust to renames
            event = TimelineEvent.objects.filter(
                people=self,
                is_auto_generated=True
            ).filter(models.Q(title__icontains='birth')).first()

            if not event:
                event = TimelineEvent.objects.create(
                    title=birth_title,
                    is_auto_generated=True,
                    owner=self.owner,
                    start_date=self.birth_date or '1900-01-01',
                    description=f"Automatic event for the birth of {self.name}."
                )
                event.people.add(self)
            
            # Update fields
            event.title = birth_title
            event.owner = self.owner
            event.start_date = self.birth_date or event.start_date
            event.start_date_precision = self.birth_date_precision or 'exact'
            event.start_date_granularity = self.birth_date_granularity or 'day'
            event.start_date_source = self.birth_date_source
            event.location = self.birth_location
            event.location_source = self.birth_location_source
            event.save()

        # Handle Death Event
        if self.death_date or self.death_location:
            death_title = f"Death of {self.name}"
            # Find by people link + auto-flag + title keywords
            event = TimelineEvent.objects.filter(
                people=self,
                is_auto_generated=True
            ).filter(models.Q(title__icontains='death')).first()

            if not event:
                event = TimelineEvent.objects.create(
                    title=death_title,
                    is_auto_generated=True,
                    owner=self.owner,
                    start_date=self.death_date or '1900-01-01',
                    description=f"Automatic event for the death of {self.name}."
                )
                event.people.add(self)
            
            # Update fields
            event.title = death_title
            event.owner = self.owner
            event.start_date = self.death_date or event.start_date
            event.start_date_precision = self.death_date_precision or 'exact'
            event.start_date_granularity = self.death_date_granularity or 'day'
            event.start_date_source = self.death_date_source
            event.location = self.death_location
            event.location_source = self.death_location_source
            event.save()

    def get_relationships(self, relationship_cache=None):
        """
        Returns a list of relationship objects, including explicit, inverse,
        and automatically detected sibling relationships.
        
        Args:
            relationship_cache: Optional list of all relevant PersonRelationship 
                              objects to avoid per-call database queries.
        """
        relationships = []
        seen = set()

        inverses = {
            'parent': 'child',
            'child': 'parent',
            'spouse': 'spouse',
            'sibling': 'sibling',
            'other': 'other'
        }

        # 1. Process relationships
        if relationship_cache is not None:
            # Filter the cache in-memory for performance
            from_rels = [r for r in relationship_cache if r.from_person_id == self.id]
            to_rels = [r for r in relationship_cache if r.to_person_id == self.id]
        else:
            from_rels = self.relationships_from.all()
            to_rels = self.relationships_to.all()

        for rel in from_rels:
            target_role = inverses.get(rel.relationship_type, 'other')
            relationships.append({
                'to_person': rel.to_person,
                'relationship_type': target_role,
                'start_date': rel.start_date,
                'start_date_precision': getattr(rel, 'start_date_precision', 'exact'),
                'start_date_granularity': getattr(rel, 'start_date_granularity', 'day'),
                'end_date': rel.end_date,
                'end_date_precision': getattr(rel, 'end_date_precision', 'exact'),
                'end_date_granularity': getattr(rel, 'end_date_granularity', 'day'),
                'notes': rel.notes,
                'is_auto': False
            })
            seen.add((rel.to_person_id, target_role))

        for rel in to_rels:
            source_role = rel.relationship_type
            if (rel.from_person_id, source_role) not in seen:
                relationships.append({
                    'to_person': rel.from_person,
                    'relationship_type': source_role,
                    'start_date': rel.start_date,
                    'start_date_precision': getattr(rel, 'start_date_precision', 'exact'),
                    'start_date_granularity': getattr(rel, 'start_date_granularity', 'day'),
                    'end_date': rel.end_date,
                    'end_date_precision': getattr(rel, 'end_date_precision', 'exact'),
                    'end_date_granularity': getattr(rel, 'end_date_granularity', 'day'),
                    'notes': rel.notes,
                    'is_auto': True
                })
                seen.add((rel.from_person_id, source_role))

        # 2. Automatic Sibling Detection (Shared parents)
        # To keep this optimized, we only do this if we have the cache or a small number of parents
        parent_ids = set()
        for rel in relationships:
            if rel['relationship_type'] == 'parent':
                parent_ids.add(rel['to_person'].id)

        if parent_ids:
            if relationship_cache is not None:
                # Find siblings from cache
                potential_siblings = set()
                for rel in relationship_cache:
                    if rel.relationship_type in ['parent', 'child']:
                        # Someone is a sibling if they have one of my parents as their parent
                        # Case A: rel.from_person is the parent (type=parent) and rel.to_person is the sibling
                        if rel.relationship_type == 'parent' and rel.from_person_id in parent_ids:
                            potential_siblings.add(rel.to_person)
                        # Case B: rel.to_person is the parent (type=child) and rel.from_person is the sibling
                        elif rel.relationship_type == 'child' and rel.to_person_id in parent_ids:
                            potential_siblings.add(rel.from_person)
                
                for sibling in potential_siblings:
                    if sibling.id != self.id and (sibling.id, 'sibling') not in seen:
                        relationships.append({
                            'to_person': sibling,
                            'relationship_type': 'sibling',
                            'is_auto': True,
                            'notes': 'Automatically detected via shared parents (cached)'
                        })
                        seen.add((sibling.id, 'sibling'))
            else:
                # Fallback to query if no cache
                siblings = Person.objects.filter(
                    models.Q(relationships_to__from_person_id__in=parent_ids, relationships_to__relationship_type='parent') |
                    models.Q(relationships_from__to_person_id__in=parent_ids, relationships_from__relationship_type='child')
                ).exclude(id=self.id).distinct()

                for sibling in siblings:
                    if (sibling.id, 'sibling') not in seen:
                        relationships.append({
                            'to_person': sibling,
                            'relationship_type': 'sibling',
                            'is_auto': True,
                            'notes': 'Automatically detected via shared parents'
                        })
                        seen.add((sibling.id, 'sibling'))
        return relationships

    def get_family_tree_data(self, relationship_cache=None):
        """
        Builds a 5-generation family tree snapshot centred on this person:

            grandparents → parents → (self + siblings) → children → grandchildren

        Spouses at each tier are included as well. The crawl is strictly
        bounded so response size is predictable regardless of dataset size.

        Args:
            relationship_cache: Optional pre-built index ``{'from': {id: [rel, ...]},
                                'to': {id: [rel, ...]}}`` created by the view layer
                                to avoid per-person database queries. If omitted,
                                the method issues its own queries.
        """
        nodes = {}   # person_id → {id, name, dates}
        links = set()  # (source_id, target_id, 'parent'|'spouse')

        # ------------------------------------------------------------------
        # Cache-aware helpers
        # ------------------------------------------------------------------

        def _rels_from(person):
            """All PersonRelationship rows where this person is the subject."""
            if relationship_cache is not None:
                return relationship_cache['from'].get(person.id, [])
            return list(person.relationships_from.select_related('to_person').all())

        def _rels_to(person):
            """All PersonRelationship rows where this person is the object."""
            if relationship_cache is not None:
                return relationship_cache['to'].get(person.id, [])
            return list(person.relationships_to.select_related('from_person').all())

        def _node(p):
            """Register a person in the nodes dict if not already present."""
            if p and p.id not in nodes:
                dates = ""
                if p.birth_date or p.death_date:
                    birth = p.birth_date.year if p.birth_date else ""
                    death = p.death_date.year if p.death_date else ""
                    dates = f" ({birth}–{death})"
                nodes[p.id] = {'id': p.id, 'name': p.name, 'dates': dates}

        def _link_parent(parent_id, child_id):
            links.add((parent_id, child_id, 'parent'))

        def _link_spouse(a_id, b_id):
            # Deterministic ordering prevents duplicate undirected spouse edges.
            ids = sorted([a_id, b_id])
            links.add((ids[0], ids[1], 'spouse'))

        def _parents_of(person):
            """
            Returns persons who are parents of ``person``.

            DB convention: PersonRelationship(from_person=Parent, type='parent', to_person=Child).
              - from_rels where type='child'  → self IS child OF to_person  → to_person is a parent
              - to_rels   where type='parent' → from_person IS parent OF self → from_person is a parent
            """
            parents = []
            for r in _rels_from(person):
                if r.relationship_type == 'child':
                    parents.append(r.to_person)
            for r in _rels_to(person):
                if r.relationship_type == 'parent':
                    parents.append(r.from_person)
            return parents

        def _children_of(person):
            """
            Returns persons who are children of ``person``.

            DB convention: PersonRelationship(from_person=Parent, type='parent', to_person=Child).
              - from_rels where type='parent' → self IS parent OF to_person → to_person is a child
              - to_rels   where type='child'  → from_person IS child OF self  → from_person is a child
            """
            children = []
            for r in _rels_from(person):
                if r.relationship_type == 'parent':
                    children.append(r.to_person)
            for r in _rels_to(person):
                if r.relationship_type == 'child':
                    children.append(r.from_person)
            return children

        def _spouses_of(person):
            """Returns persons who are spouses of ``person``."""
            spouses = []
            for r in _rels_from(person):
                if r.relationship_type == 'spouse':
                    spouses.append(r.to_person)
            for r in _rels_to(person):
                if r.relationship_type == 'spouse':
                    spouses.append(r.from_person)
            return spouses

        # ------------------------------------------------------------------
        # Build the tree tier by tier
        # ------------------------------------------------------------------

        _node(self)

        # Spouses of self
        for spouse in _spouses_of(self):
            _node(spouse)
            _link_spouse(self.id, spouse.id)

        # Tier +1: Parents (and their spouses / step-parents)
        parents = _parents_of(self)
        for parent in parents:
            _node(parent)
            _link_parent(parent.id, self.id)
            for ps in _spouses_of(parent):
                if ps.id != self.id:
                    _node(ps)
                    _link_spouse(parent.id, ps.id)

            # Siblings: other children of this parent
            for sibling in _children_of(parent):
                if sibling.id != self.id:
                    _node(sibling)
                    _link_parent(parent.id, sibling.id)
                    for ss in _spouses_of(sibling):
                        _node(ss)
                        _link_spouse(sibling.id, ss.id)

            # Tier +2: Grandparents (and their spouses)
            for gp in _parents_of(parent):
                _node(gp)
                _link_parent(gp.id, parent.id)
                for gs in _spouses_of(gp):
                    if gs.id != parent.id:
                        _node(gs)
                        _link_spouse(gp.id, gs.id)

        # Tier −1: Children (and co-parents, spouses)
        children = _children_of(self)
        for child in children:
            _node(child)
            _link_parent(self.id, child.id)
            # Include other parent(s) of this child
            for other_parent in _parents_of(child):
                if other_parent.id != self.id:
                    _node(other_parent)
                    _link_parent(other_parent.id, child.id)
                    _link_spouse(self.id, other_parent.id)
            for cs in _spouses_of(child):
                _node(cs)
                _link_spouse(child.id, cs.id)

            # Tier −2: Grandchildren (and their spouses)
            for gc in _children_of(child):
                _node(gc)
                _link_parent(child.id, gc.id)
                for gs in _spouses_of(gc):
                    _node(gs)
                    _link_spouse(gc.id, gs.id)

        return {
            'nodes': list(nodes.values()),
            'links': [{'source': l[0], 'target': l[1], 'type': l[2]} for l in links],
            'current_person_id': self.id
        }

class PersonRelationship(models.Model):
    RELATIONSHIP_CHOICES = [
        ('parent', 'Parent'),
        ('child', 'Child'),
        ('spouse', 'Spouse'),
        ('sibling', 'Sibling'),
        ('other', 'Other'),
    ]
    from_person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='relationships_from')
    to_person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='relationships_to')
    relationship_type = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES)
    start_date = models.DateField(blank=True, null=True, help_text="e.g. Marriage date")
    start_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    start_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    end_date = models.DateField(blank=True, null=True, help_text="e.g. Divorce date")
    end_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    end_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return f"{self.from_person} is {self.relationship_type} of {self.to_person}"

class Timeline(models.Model):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    description = models.TextField(blank=True, null=True, help_text=MARKDOWN_HELP_TEXT)
    is_default = models.BooleanField(default=False, help_text="If true, this timeline will automatically load for new visitors.")
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='timelines', null=True, blank=True)
    cloned_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='clones')
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")

    def __str__(self):
        if self.parent:
            return f"{self.parent} > {self.name}"
        return self.name

    class Meta:
        ordering = ['name']

class TimelineEvent(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(help_text=MARKDOWN_HELP_TEXT)
    description_sources = models.ManyToManyField('Source', blank=True, related_name='+')
    start_date = models.DateField(help_text="Requires at least a start date", db_index=True)
    start_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    start_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    start_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    end_date = models.DateField(blank=True, null=True, help_text="Leave empty for a point event")
    end_date_precision = models.CharField(max_length=10, choices=DATE_PRECISION_CHOICES, default='exact', blank=True, null=True)
    end_date_granularity = models.CharField(max_length=10, choices=DATE_GRANULARITY_CHOICES, default='day', blank=True, null=True)
    end_date_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, blank=True, null=True, related_name='events')
    location_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    end_location = models.ForeignKey(Location, on_delete=models.SET_NULL, blank=True, null=True, related_name='events_ending_here', help_text="Optional destination for travel/journeys")
    end_location_source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    people = models.ManyToManyField(Person, blank=True, related_name='events')
    timelines = models.ManyToManyField(Timeline, blank=True, related_name='events')
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    link = models.URLField(blank=True, null=True, help_text="Primary external link")
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unverified', db_index=True)
    is_auto_generated = models.BooleanField(default=False, help_text="True if created automatically (e.g. births/deaths)", db_index=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    cloned_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='clones')
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='tagged_events')
    
    disputed_facts = GenericRelation('DisputedFact')
    public_comments = GenericRelation('PublicComment')
    research_questions = GenericRelation('ResearchQuestion')
    history = HistoricalRecords(excluded_fields=['updated_at'])
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-start_date', 'title']

class Story(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True, help_text=MARKDOWN_HELP_TEXT)
    color = models.CharField(max_length=50, default="#8B5CF6", help_text="Hex color code (e.g. #8B5CF6) or Tailwind color class")
    researcher_notes = models.TextField(blank=True, null=True, help_text="Private notes for research follow-up")
    needs_research = models.BooleanField(default=False, help_text="Flag for researcher follow-up")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stories', null=True, blank=True)
    cloned_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='clones')
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='stories')
    is_private = models.BooleanField(default=False, help_text="Check to hide this item from public view")
    
    public_comments = GenericRelation('PublicComment')
    research_questions = GenericRelation('ResearchQuestion')
    
    def __str__(self):
        return self.title

    class Meta:
        ordering = ['title']
        verbose_name_plural = "Stories"

class StoryEvent(models.Model):
    """
    Junction model linking a TimelineEvent to a Story.
    The ``sequence`` field provides a manual ordering override so that events
    on the same date can be arranged in a deliberate narrative order.
    """
    story = models.ForeignKey(Story, on_delete=models.CASCADE)
    event = models.ForeignKey(TimelineEvent, on_delete=models.CASCADE)
    sequence = models.IntegerField(default=0, help_text="Manual override for ordering events exactly on the same date")

    class Meta:
        ordering = ['sequence']
        unique_together = ('story', 'event')


class EventImage(models.Model):
    """
    An additional image attached to a TimelineEvent.
    The primary event image lives on ``TimelineEvent.image``; this model holds
    the gallery of supplementary images accessible via ``related_name='additional_images'``.
    """
    event = models.ForeignKey(TimelineEvent, on_delete=models.CASCADE, related_name='additional_images')
    image = models.ImageField(upload_to='event_images/')
    caption = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Image for {self.event.title}"

class Attachment(models.Model):
    """
    A file attachment that can be linked to multiple entity types simultaneously.

    The M2M relationships to ``TimelineEvent``, ``Person``, ``Location``, and
    ``Source`` use ``blank=True`` so an attachment can belong to any combination
    of entity types (e.g. an audio recording that is both a primary source and
    associated with an event). Ownership (``owner``) controls edit permissions.
    """
    FILE_TYPES = [
        ('document', 'Document'),
        ('audio', 'Audio'),
        ('video', 'Video'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='attachments/')
    file_type = models.CharField(max_length=20, choices=FILE_TYPES)
    description = models.TextField(blank=True, null=True, help_text=MARKDOWN_HELP_TEXT)

    events = models.ManyToManyField(TimelineEvent, blank=True, related_name='attachments')
    people = models.ManyToManyField(Person, blank=True, related_name='attachments')
    locations = models.ManyToManyField(Location, blank=True, related_name='attachments')
    sources = models.ManyToManyField('Source', blank=True, related_name='attachments')

    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)

    def __str__(self):
        return f"{self.get_file_type_display()}: {self.title}"


class DisputedFact(models.Model):
    """
    Records a secondary or disputed claim (e.g., an alternative date, location, or spelling)
    linked to any entity (Person, Location, TimelineEvent).
    """
    DISPUTED_FIELD_CHOICES = [
        ('start_date', 'Start Date'),
        ('end_date', 'End Date'),
        ('established_date', 'Established Date'),
        ('ceased_date', 'Ceased Date'),
        ('birth_date', 'Birth Date'),
        ('death_date', 'Death Date'),
        ('description', 'Description'),
        ('location', 'Location'),
        ('name', 'Name'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    field_name = models.CharField(max_length=50, choices=DISPUTED_FIELD_CHOICES, help_text="Select the field that is disputed")
    alternative_value = models.TextField(help_text="The contested value or interpretation")
    source = models.ForeignKey('Source', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notes = models.TextField(blank=True, null=True, help_text="Explanation of the dispute")
    
    is_resolved = models.BooleanField(default=False, help_text="Check if this dispute has been settled")
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='disputed_facts', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    
    history = HistoricalRecords()

    def __str__(self):
        return f"Disputed {self.field_name}: {self.alternative_value}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

class PublicComment(models.Model):
    """
    Publicly submitted comments or corrections on timeline entities.
    Must be approved by the data owner before being visible.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('spam', 'Spam/Rejected'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    author_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True, help_text="Optional email for the researcher to reply")
    body = models.TextField(help_text="The comment or correction content")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    # Denormalized owner field for easy admin filtering without complex GenericForeignKey queries
    target_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_comments', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def save(self, *args, **kwargs):
        # Auto-stamp the target owner if not set, by checking the related content_object
        if not self.target_owner and self.content_object and hasattr(self.content_object, 'owner'):
            self.target_owner = self.content_object.owner
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Comment by {self.author_name} [{self.get_status_display()}]"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]


class ResearchQuestion(models.Model):
    """
    Open tasks or questions a Researcher creates for their own follow-up.
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('answered', 'Answered/Resolved'),
        ('deferred', 'Deferred'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    question = models.TextField()
    answer = models.TextField(blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium', db_index=True)
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='research_questions', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_status_display()} Question"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]
# ---------------------------------------------------------------------------
# Help & Documentation
# ---------------------------------------------------------------------------

class HelpCategory(models.Model):
    """
    Groups help topics (e.g., 'Getting Started', 'Advanced Features').
    """
    name = models.CharField(max_length=100)
    order = models.IntegerField(default=0)
    
    class Meta:
        verbose_name_plural = "Help Categories"
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.name

class HelpTopic(models.Model):
    """
    Individual help pages with markdown content.
    """
    category = models.ForeignKey(HelpCategory, on_delete=models.CASCADE, related_name='topics')
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    content = models.TextField(help_text="Markdown supported")
    order = models.IntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'category__name', 'order', 'title']

    def __str__(self):
        return f"{self.category} > {self.title}"

class HelpImage(models.Model):
    """
    Images/Screenshots associated with a help topic.
    """
    topic = models.ForeignKey(HelpTopic, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='help_images/')
    caption = models.CharField(max_length=255, blank=True)
    
    def __str__(self):
        return f"Image for {self.topic.title}"
