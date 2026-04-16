from .models import Tag, Source, Location, Person, Timeline, TimelineEvent, Story, StoryEvent, Attachment, format_date_with_precision



def _safe_image_url(image_field, relative=False):
    """
    Returns the URL of an ImageField, or the relative filesystem path if relative=True.
    Returns None if the field is empty.
    """
    if not image_field:
        return None
    if relative:
        return image_field.name
    try:
        return image_field.url
    except ValueError:
        return None

def serialize_tags(tags_manager):
    """
    Serializes a queryset of Tags into a list of dictionaries.
    """
    return [{'id': tag.id, 'name': tag.name, 'color': tag.color} for tag in tags_manager.all()]

def serialize_attachments(attachments_manager, include_private=False):
    """
    Serializes a queryset of Attachments, ensuring file URLs are handled safely.
    """
    return [
        {
            'id': attachment.id, 
            'title': attachment.title, 
            'url': attachment.file.url if attachment.file else None, 
            'relative_path': attachment.file.name if attachment.file and include_private else None,
            'type': attachment.file_type, 
            'description': attachment.description
        } for attachment in attachments_manager.all()
    ]

def serialize_disputed_facts(disputed_facts_manager, sources_cache=None):
    from collections import defaultdict
    disputes = defaultdict(list)
    for df in disputed_facts_manager.all():
        if not df.is_resolved:
            disputes[df.field_name].append({
                'alternative_value': df.alternative_value,
                'source': serialize_source(df.source, sources_cache),
                'notes': df.notes
            })
    return dict(disputes)

def serialize_public_comments(comments_manager):
    return [
        {
            'author_name': c.author_name,
            'body': c.body,
            'created_at': c.created_at.isoformat()
        }
        for c in comments_manager.all() if c.status == 'approved'
    ]

def serialize_research_questions(questions_manager, request_user=None):
    if not request_user or not request_user.is_authenticated:
        return []
    return [
        {
            'id': rq.id,
            'question': rq.question,
            'answer': rq.answer,
            'status': rq.status,
            'created_at': rq.created_at.isoformat()
        }
        for rq in questions_manager.all() 
        if rq.owner == request_user and rq.status == 'open'
    ]

def serialize_source(source, sources_cache=None, include_private=False, request_user=None):
    """
    Serializes a Source. Uses a cache to avoid duplicate objects in the main entities list.
    """
    if not source:
        return None
    
    if sources_cache is not None and source.id not in sources_cache:
        data = {
            'id': source.id,
            'title': source.title,
            'author': source.author,
            'url': source.url,
            'publication_date': source.publication_date,
            'parent_title': source.parent.title if source.parent else None,
            'tags': serialize_tags(source.tags),
            'attachments': serialize_attachments(source.attachments, include_private),
            'is_private': source.is_private,
        }
        if include_private:
            data.update({
                'researcher_notes': source.researcher_notes,
                'needs_research': source.needs_research,
                'owner': source.owner.username if source.owner else None,
                'created_at': source.created_at.isoformat() if source.created_at else None,
            })
        sources_cache[source.id] = data
    
    return {'id': source.id, 'title': source.title}

def resolve_location_name(location, event_date=None):
    if not location:
        return None
    if isinstance(location, str):
        return location
    if not event_date:
        return location.name
    
    try:
        # Use .all() which is prefetched in the view
        aliases = location.aliases.all()
    except AttributeError:
        return location.name
        
    for alias in aliases:
        valid_from = alias.valid_from
        valid_to = alias.valid_to
        
        # If both are null, it's a permanent alias or we don't know the range
        if not valid_from and not valid_to:
            return alias.name
            
        # Check ranges if they exist
        is_after_start = True
        if valid_from and event_date < valid_from:
            is_after_start = False
            
        is_before_end = True
        if valid_to and event_date > valid_to:
            is_before_end = False
            
        if is_after_start and is_before_end:
            return alias.name
             
    return location.name

def resolve_location_full_name(location, event_date=None):
    if not location:
        return None
    if isinstance(location, str):
        return location
        
    local_name = resolve_location_name(location, event_date)
    if hasattr(location, 'parent') and location.parent:
        parent_name = resolve_location_full_name(location.parent, event_date)
        return f"{parent_name} > {local_name}"
    return local_name

def serialize_location_alias(alias):
    return {
        'name': alias.name,
        'valid_from': alias.valid_from.isoformat() if alias.valid_from else None,
        'valid_to': alias.valid_to.isoformat() if alias.valid_to else None,
    }

def serialize_location(location, sources_cache=None, event_date=None, request_user=None, include_private=False):
    """
    Serializes a Location, including its aliases and research metadata.
    """
    if not location:
        return None
    
    image_url = _safe_image_url(location.image)
    image_path = _safe_image_url(location.image, relative=True) if include_private else None

    resolved_short_name = resolve_location_name(location, event_date)
    resolved_full_name = resolve_location_full_name(location, event_date)

    data = {
        'id': location.id,
        'name': location.name, # Base name for re-linking
        'display_name': resolved_full_name,
        'parent_name': location.parent.name if location.parent else None,
        'coordinates': location.coordinates,
        'coordinates_source': serialize_source(location.coordinates_source, sources_cache, include_private),
        'description': location.description,
        'description_sources': [serialize_source(s, sources_cache, include_private)['id'] for s in location.description_sources.all()],
        'image': image_url,
        'link': location.link,
        'established_date': location.established_date.isoformat() if location.established_date else None,
        'established_date_precision': location.established_date_precision,
        'established_date_granularity': location.established_date_granularity,
        'established_date_source': serialize_source(location.established_date_source, sources_cache, include_private),
        'ceased_date': location.ceased_date.isoformat() if location.ceased_date else None,
        'ceased_date_precision': location.ceased_date_precision,
        'ceased_date_granularity': location.ceased_date_granularity,
        'ceased_date_source': serialize_source(location.ceased_date_source, sources_cache, include_private),
        'status': location.status,
        'owner': location.owner.username if location.owner else None,
        'tags': serialize_tags(location.tags),
        'attachments': serialize_attachments(location.attachments, include_private),
        'aliases': [serialize_location_alias(a) for a in location.aliases.all()],
        'disputed_facts': serialize_disputed_facts(location.disputed_facts, sources_cache),
        'public_comments': serialize_public_comments(location.public_comments),
        'research_questions': serialize_research_questions(location.research_questions, request_user),
        'is_private': location.is_private,
    }

    if include_private:
        data.update({
            'image_path': image_path,
            'researcher_notes': location.researcher_notes,
            'needs_research': location.needs_research,
            'created_at': location.created_at.isoformat() if location.created_at else None,
        })

    return data

def serialize_person(person, sources_cache=None, include_details=True, relationship_cache=None, request_user=None, include_private=False):
    """
    Serializes a Person. Supports Full Archive parity.
    """
    if not person:
        return None
    
    data = {
        'id': person.id,
        'name': person.name,
        'is_private': person.is_private,
    }
    
    if include_details:
        relationships_data = []
        for r in person.get_relationships():
            relationships_data.append({
                'to_person': r['to_person'].name,
                'to_person_id': r['to_person'].id,
                'type': r['relationship_type'],
                # Legacy UI Compatibility
                'start': r['start_date'].isoformat() if r.get('start_date') else None,
                'end': r['end_date'].isoformat() if r.get('end_date') else None,
                # Deep Archive Parity
                'start_date': r['start_date'].isoformat() if r.get('start_date') else None,
                'end_date': r['end_date'].isoformat() if r.get('end_date') else None,
                'notes': r.get('notes'),
                'is_auto': r.get('is_auto', False)
            })
            
        data.update({
            'gender': person.gender,
            'gender_custom': person.gender_custom,
            'status': person.status,
            'disambiguation': person.disambiguation,
            'description': person.description,
            'description_sources': [serialize_source(s, sources_cache, include_private)['id'] for s in person.description_sources.all()],
            'image': _safe_image_url(person.image),
            'link': person.link,
            'birth_date': person.birth_date.isoformat() if person.birth_date else None,
            'birth_date_precision': person.birth_date_precision,
            'birth_date_granularity': person.birth_date_granularity,
            'birth_date_source': serialize_source(person.birth_date_source, sources_cache, include_private),
            'birth_location_name': person.birth_location.name if person.birth_location else None,
            'birth_location_source': serialize_source(person.birth_location_source, sources_cache, include_private),
            'death_date': person.death_date.isoformat() if person.death_date else None,
            'death_date_precision': person.death_date_precision,
            'death_date_granularity': person.death_date_granularity,
            'death_date_source': serialize_source(person.death_date_source, sources_cache, include_private),
            'death_location_name': person.death_location.name if person.death_location else None,
            'death_location_source': serialize_source(person.death_location_source, sources_cache, include_private),
            'burial_location': person.burial_location,
            'burial_location_source': serialize_source(person.burial_location_source, sources_cache, include_private),
            'relationships': relationships_data,
            'tags': serialize_tags(person.tags),
            'attachments': serialize_attachments(person.attachments, include_private),
            'disputed_facts': serialize_disputed_facts(person.disputed_facts, sources_cache),
            'public_comments': serialize_public_comments(person.public_comments),
            'research_questions': serialize_research_questions(person.research_questions, request_user)
        })

        if include_private:
            data.update({
                'image_path': _safe_image_url(person.image, relative=True),
                'researcher_notes': person.researcher_notes,
                'needs_research': person.needs_research,
                'owner': person.owner.username if person.owner else None,
                'created_at': person.created_at.isoformat() if person.created_at else None,
            })
    
    return data

def serialize_timeline(timeline, include_private=False):
    data = {
        'id': timeline.id,
        'name': timeline.name,
        'parent_name': timeline.parent.name if timeline.parent else None,
        'description': timeline.description,
        'is_default': timeline.is_default,
        'is_private': timeline.is_private,
        'owner': timeline.owner.username if timeline.owner else None,
    }
    if include_private:
        data.update({
            'researcher_notes': timeline.researcher_notes,
            'needs_research': timeline.needs_research,
            'created_at': timeline.created_at.isoformat() if timeline.created_at else None,
        })
    return data

def serialize_person_relationship(rel):
    return {
        'from_person_name': rel.from_person.name,
        'to_person_name': rel.to_person.name,
        'relationship_type': rel.relationship_type,
        'start_date': rel.start_date.isoformat() if rel.start_date else None,
        'start_date_precision': rel.start_date_precision,
        'start_date_granularity': rel.start_date_granularity,
        'end_date': rel.end_date.isoformat() if rel.end_date else None,
        'end_date_precision': rel.end_date_precision,
        'end_date_granularity': rel.end_date_granularity,
        'notes': rel.notes,
    }

def serialize_story(story, request_user=None, include_private=False):
    """
    Serializes a Story with owner and tags.
    Note: uses ``'title'`` (not ``'name'``) to match the Story model field.
    """
    data = {
        'id': story.id,
        'title': story.title,
        'description': story.description,
        'color': story.color,
        'tags': serialize_tags(story.tags),
        'owner': story.owner.username if story.owner else None,
        'public_comments': serialize_public_comments(story.public_comments),
        'research_questions': serialize_research_questions(story.research_questions, request_user)
    }

    if include_private:
        data.update({
            'researcher_notes': story.researcher_notes,
            'needs_research': story.needs_research,
            'is_private': story.is_private,
        })
    return data

def serialize_event(event, sources_cache=None, request_user=None, include_private=False):
    """
    Serializes a TimelineEvent with 100% field parity for Deep Archive.
    """
    is_stale = False
    if event.cloned_from and event.cloned_from.updated_at and event.updated_at:
        if event.cloned_from.updated_at > event.updated_at:
            is_stale = True

    images = []
    main_url = _safe_image_url(event.image)
    main_path = _safe_image_url(event.image, relative=True) if include_private else None
    
    if main_url:
        images.append({'url': main_url, 'path': main_path, 'caption': event.title})

    featured_url = main_url
    for img in event.additional_images.all():
        url = _safe_image_url(img.image)
        path = _safe_image_url(img.image, relative=True) if include_private else None
        if url and url != featured_url:
            images.append({'url': url, 'path': path, 'caption': img.caption or event.title})

    data = {
        'id': event.id,
        # Legacy UI Compatibility (Vis.js requires 'content' and 'start')
        'content': event.title,
        'start': event.start_date.isoformat(),
        'end': event.end_date.isoformat() if event.end_date else None,
        # Tooltip for vis.js
        'title': event.description[:100] + '...' if event.description else event.title,

        # Deep Archive Parity (Field-accurate names)
        'event_title': event.title,
        'description': event.description,
        'start_date': event.start_date.isoformat(),
        'start_date_precision': event.start_date_precision,
        'start_date_granularity': event.start_date_granularity,
        'start_date_source': serialize_source(event.start_date_source, sources_cache, include_private),
        'end_date': event.end_date.isoformat() if event.end_date else None,
        'end_date_precision': event.end_date_precision,
        'end_date_granularity': event.end_date_granularity,
        'end_date_source': serialize_source(event.end_date_source, sources_cache, include_private),
        'location_name': event.location.name if event.location else None,
        'location_source': serialize_source(event.location_source, sources_cache, include_private),
        'end_location_name': event.end_location.name if event.end_location else None,
        'end_location_source': serialize_source(event.end_location_source, sources_cache, include_private),
        'owner': event.owner.username if event.owner else None,
        'status': event.status,
        'is_private': event.is_private,
        'is_auto_generated': event.is_auto_generated,
        'timelines': [tl.name for tl in event.timelines.all()],
        'people': [p.name for p in event.people.all()],
        'tags': serialize_tags(event.tags),
        'description_sources': [serialize_source(s, sources_cache, include_private)['id'] for s in event.description_sources.all()],
        'attachments': serialize_attachments(event.attachments, include_private),
        'disputed_facts': serialize_disputed_facts(event.disputed_facts, sources_cache),
        'images': images,
        'link': event.link,
        'stories': [], # Filled by view
    }

    if include_private:
        data.update({
            'image_path': main_path,
            'researcher_notes': event.researcher_notes,
            'needs_research': event.needs_research,
            'created_at': event.created_at.isoformat() if event.created_at else None,
        })
    
    return data
