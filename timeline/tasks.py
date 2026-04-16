from background_task import background
from django.contrib.auth import get_user_model

@background(schedule=1)
def process_full_deep_copy(timeline_id, user_id):
    from timeline.models import Timeline, TimelineEvent
    
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
        original_timeline = Timeline.objects.get(pk=timeline_id)
    except (User.DoesNotExist, Timeline.DoesNotExist):
        return

    # 1. Copy the timeline itself
    new_timeline = Timeline.objects.get(pk=timeline_id)
    new_timeline.pk = None
    new_timeline.owner = user
    new_timeline.cloned_from = original_timeline
    new_timeline.name = f"{original_timeline.name} (Copy)"
    new_timeline.save()
    
    # Pre-collect stories to clone them only once per timeline
    events_to_copy = TimelineEvent.objects.filter(timelines__id=timeline_id)
    story_map = {} # old_story_id -> new_story
    from timeline.models import Story, StoryEvent
    
    for event in events_to_copy:
        for story_event in StoryEvent.objects.filter(event=event):
            old_story = story_event.story
            if old_story.id not in story_map:
                new_story = Story.objects.get(pk=old_story.id)
                new_story.pk = None
                new_story.owner = user
                new_story.cloned_from = old_story
                new_story.researcher_notes = ""
                new_story.needs_research = False
                new_story.save()
                story_map[old_story.id] = new_story

    # 2. Copy all events in this timeline
    for event in events_to_copy:
        # Shallow copy the event
        old_event_pk = event.pk
        original_event = TimelineEvent.objects.get(pk=old_event_pk)
        new_event = event
        new_event.pk = None
        new_event.owner = user
        new_event.cloned_from = original_event
        new_event.researcher_notes = ""
        new_event.needs_research = False
        new_event.save()
        
        # Link to the NEW timeline ONLY
        new_event.timelines.set([new_timeline])
        
        # Copy M2M relationships (People)
        new_event.people.set(original_event.people.all())
        
        # Copy additional images if they exist
        for img in original_event.additional_images.all():
            img.pk = None
            img.event = new_event
            img.save()
            
        # Link new event to the new cloned stories
        for old_se in StoryEvent.objects.filter(event=original_event):
            new_story = story_map.get(old_se.story.id)
            if new_story:
                StoryEvent.objects.create(
                    story=new_story,
                    event=new_event,
                    sequence=old_se.sequence
                )

