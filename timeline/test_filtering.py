from django.test import TestCase, Client
from django.urls import reverse
from .models import TimelineEvent, Location, Person, Timeline, Tag, Story, StoryEvent
from datetime import date
from django.core.cache import cache

class LogicalFilteringTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        
        # Setup Timelines
        self.tl_main = Timeline.objects.create(name="Main Timeline")
        self.tl_other = Timeline.objects.create(name="Other Timeline")
        
        # Setup People
        self.person_a = Person.objects.create(name="Person A", birth_date=date(1800, 1, 1))
        self.person_b = Person.objects.create(name="Person B", birth_date=date(1850, 1, 1))
        
        # Setup Stories
        self.story_x = Story.objects.create(title="Story X")
        
        # Setup Events
        # Event 1: In Main Timeline
        self.event_1 = TimelineEvent.objects.create(
            title="Event 1", start_date=date(1900, 1, 1)
        )
        self.event_1.timelines.add(self.tl_main)
        self.event_1.people.add(self.person_a)
        
        # Event 2: In Main Timeline AND Story X
        self.event_2 = TimelineEvent.objects.create(
            title="Event 2", start_date=date(1910, 1, 1)
        )
        self.event_2.timelines.add(self.tl_main)
        StoryEvent.objects.create(story=self.story_x, event=self.event_2, sequence=1)
        
        # Event 3: In Other Timeline ONLY
        self.event_3 = TimelineEvent.objects.create(
            title="Event 3", start_date=date(1920, 1, 1)
        )
        self.event_3.timelines.add(self.tl_other)
        
        # Event 4: In Other Timeline AND Story X
        self.event_4 = TimelineEvent.objects.create(
            title="Event 4", start_date=date(1930, 1, 1)
        )
        self.event_4.timelines.add(self.tl_other)
        StoryEvent.objects.create(story=self.story_x, event=self.event_4, sequence=2)

    def test_additive_timelines(self):
        """Selecting multiple timelines should be additive."""
        # Only Main (with auto-events disabled for exact count)
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 2) # Event 1, Event 2
        
        # Both (with auto-events disabled)
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&timeline={self.tl_other.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 4)

    def test_subtractive_stories(self):
        """Stories should act as a subtractive mask on the selected timelines."""
        # Select both timelines, but mask for Story X (Auto events disabled for clarity)
        # Events 2 and 4 are in Story X
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&timeline={self.tl_other.id}&story={self.story_x.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 2)
        titles = [e['content'] for e in events]
        self.assertIn("Event 2", titles)
        self.assertIn("Event 4", titles)
        
        # Select ONLY Main Timeline, mask for Story X
        # Only Event 2 should remain
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&story={self.story_x.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['content'], "Event 2")

    def test_additive_auto_events(self):
        """Birth/Death events should be added based on the people in the base timeline scope."""
        # Person A is in Event 1 (Main Timeline)
        # Their birth event (auto-generated) should appear when Main Timeline is selected + show_births_deaths=True (default)
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}")
        events = resp.json()['events']
        # Should have Event 1, Event 2, and Birth of Person A
        # (Event 2 doesn't have Person A, but Event 1 does)
        titles = [e['content'] for e in events]
        self.assertIn("Event 1", titles)
        self.assertIn("Birth of Person A", titles)
        self.assertIn("Event 2", titles)
        self.assertEqual(len(events), 3)
        
        # Person B is NOT in any event in Main Timeline. Their birth should NOT appear.
        self.assertNotIn("Birth of Person B", titles)

    def test_subtractive_person_filter(self):
        """Person filter should be subtractive on the base scope (Timeline + Auto)."""
        # Base scope: Main Timeline -> {Event 1 (Person A), Event 2 (No one), Birth A}
        # Filter for Person A
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&person={self.person_a.id}")
        events = resp.json()['events']
        # Result should be {Event 1, Birth A}
        self.assertEqual(len(events), 2)
        titles = [e['content'] for e in events]
        self.assertIn("Event 1", titles)
        self.assertIn("Birth of Person A", titles)

    def test_no_results_if_no_timeline(self):
        """If no timeline is selected, no events should return even if a story is selected."""
        resp = self.client.get(f"{reverse('events_json')}?story={self.story_x.id}")
        events = resp.json()['events']
        self.assertEqual(len(events), 0)

    def test_subtractive_location_filter(self):
        """Location filter should be subtractive on the base scope."""
        # Setup location hierarchy
        loc_parent = Location.objects.create(name="Parent Location")
        loc_child = Location.objects.create(name="Child Location", parent=loc_parent)
        
        # Event 5: In Main Timeline, at Child Location
        event_5 = TimelineEvent.objects.create(
            title="Event 5", start_date=date(1940, 1, 1), location=loc_child
        )
        event_5.timelines.add(self.tl_main)
        
        # Filter by Parent Location -> Should show Event 5 (descendant logic)
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&location={loc_parent.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['content'], "Event 5")
        
        # Filter by Child Location -> Should show Event 5
        resp = self.client.get(f"{reverse('events_json')}?timeline={self.tl_main.id}&location={loc_child.id}&show_births_deaths=false")
        events = resp.json()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['content'], "Event 5")
