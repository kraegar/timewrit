from django.test import TestCase, Client
from django.urls import reverse
from .models import TimelineEvent, Location, Person, Timeline
from .importers.csv_importer import EventImporter
import io
from datetime import date
from django.core.cache import cache

class TimelineApiTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.parent_loc = Location.objects.create(name="Arizona")
        self.child_loc = Location.objects.create(name="Tombstone", parent=self.parent_loc)
        self.person = Person.objects.create(name="Wyatt Earp")
        
        self.parent_tl = Timeline.objects.create(name="US History")
        self.child_tl = Timeline.objects.create(name="Wild West", parent=self.parent_tl)
        
        self.event_parent = TimelineEvent.objects.create(
            title="State Founded",
            description="Arizona founded",
            start_date=date(1912, 2, 14),
            location=self.parent_loc
        )
        self.event_child = TimelineEvent.objects.create(
            title="OK Corral",
            description="Gunfight",
            start_date=date(1881, 10, 26),
            location=self.child_loc
        )
        self.event_parent.timelines.add(self.parent_tl)
        self.event_child.timelines.add(self.child_tl)

    def test_events_json(self):
        response = self.client.get(reverse('events_json') + f'?timeline={self.parent_tl.id}&timeline={self.child_tl.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()['events']
        self.assertEqual(len(data), 2)

    def test_filter_by_parent_location(self):
        # Filtering by Arizona (parent) should show Arizona AND Tombstone events
        response = self.client.get(reverse('events_json') + f'?location={self.parent_loc.id}&timeline={self.parent_tl.id}&timeline={self.child_tl.id}')
        data = response.json()['events']
        self.assertEqual(len(data), 2)
        titles = [e['content'] for e in data]
        self.assertIn("State Founded", titles)
        self.assertIn("OK Corral", titles)

    def test_filter_by_child_location(self):
        # Filtering by Tombstone (child) should ONLY show Tombstone events
        response = self.client.get(reverse('events_json') + f'?location={self.child_loc.id}&timeline={self.child_tl.id}')
        data = response.json()['events']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['content'], "OK Corral")

    def test_filter_by_timeline_hierarchy(self):
        # Filter by US History (parent) -> Should include Wild West events and US History events
        response = self.client.get(reverse('events_json') + f'?timeline={self.parent_tl.id}')
        data = response.json()['events']
        self.assertEqual(len(data), 2) 
        titles = [e['content'] for e in data]
        self.assertIn("State Founded", titles)
        self.assertIn("OK Corral", titles)

    def test_filter_by_child_timeline(self):
        response = self.client.get(reverse('events_json') + f'?timeline={self.child_tl.id}')
        data = response.json()['events']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['content'], "OK Corral")

class ImportTest(TestCase):
    def test_csv_import(self):
        csv_content = "title,description,start_date,end_date,location,people,timelines\nTest Event,Desc,2023-01-01,,Test Loc,Wyatt Earp,Wild West"
        csv_file = io.BytesIO(csv_content.encode('utf-8'))
        
        importer = EventImporter(user=None)
        count, errors = importer.import_data(csv_file)
        
        self.assertEqual(count, 1)
        self.assertEqual(len(errors), 0)
        
        event = TimelineEvent.objects.first()
        self.assertEqual(event.title, "Test Event")
        self.assertEqual(event.location.name, "Test Loc")
        self.assertEqual(event.people.count(), 1)
        self.assertEqual(event.people.first().name, "Wyatt Earp")
        self.assertEqual(event.timelines.count(), 1)
        self.assertEqual(event.timelines.first().name, "Wild West")
