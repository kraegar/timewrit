import csv
import io
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from datetime import datetime
from ..models import TimelineEvent, Location, Person, Timeline, Source
from django.utils.dateparse import parse_date
from dateutil import parser as dateutil_parser

class BaseImporter(ABC):
    """
    Abstract base class for all data importers.
    """
    def __init__(self, user=None):
        self.user = user
        
    @abstractmethod
    def parse(self, file_obj) -> List[Dict[str, Any]]:
        pass

    def import_data(self, file_obj):
        parsed_data = self.parse(file_obj)
        created_count = 0
        errors = []

        for row in parsed_data:
            try:
                self.create_record(row)
                created_count += 1
            except Exception as e:
                errors.append(f"Error importing row {row}: {str(e)}")
        
        return created_count, errors

    @abstractmethod
    def create_record(self, data: Dict[str, Any]):
        pass

    def _get_or_create_sources(self, sources_str: str) -> List[Source]:
        """Parses a comma-separated string of sources and creates Source records."""
        sources = []
        if not sources_str:
            return sources
        
        names = [s.strip() for s in sources_str.split(',') if s.strip()]
        for name in names:
            source, _ = Source.objects.get_or_create(title=name)
            if not source.owner and self.user and self.user.is_authenticated:
                source.owner = self.user
                source.save()
            sources.append(source)
        return sources

    def _get_or_create_timelines(self, timelines_str: str) -> List[Timeline]:
        timelines = []
        if not timelines_str:
            return timelines
        
        names = [t.strip() for t in timelines_str.split(',') if t.strip()]
        for name in names:
            tl, _ = Timeline.objects.get_or_create(name=name)
            if not tl.owner and self.user and self.user.is_authenticated:
                tl.owner = self.user
                tl.save()
            timelines.append(tl)
        return timelines

    def _parse_date_field(self, raw: str):
        """
        Parse a date string (e.g. "1847-06-01" or "June 1, 1847").

        Returns a tuple (date | None, display: str | None).
        - date:    The parsed date or None if unparseable.
        - display: The original raw string if date was not parseable (for display).
        """
        if not raw:
            return None, None

        # Try standard ISO parse
        parsed = parse_date(raw)
        if parsed:
            return parsed, None

        # Try dateutil fuzzy parse
        try:
            parsed = dateutil_parser.parse(raw, fuzzy=True).date()
            return parsed, None
        except (ValueError, TypeError):
            return None, raw


class EventImporter(BaseImporter):
    """
    Importer for Events CSV.
    Headers: title, description, start_date, end_date, location, people, timelines, link, sources
    Supports BCE dates: e.g. "44 BCE", "44 BC", "c. 500 BCE"
    """
    def parse(self, file_obj) -> List[Dict[str, Any]]:
        if isinstance(file_obj, bytes):
            file_obj = io.StringIO(file_obj.decode('utf-8'))
        elif hasattr(file_obj, 'read'):
             content = file_obj.read().decode('utf-8')
             file_obj = io.StringIO(content)

        reader = csv.DictReader(file_obj)
        results = []
        for row in reader:
            if not row.get('title') or not row.get('start_date'):
                continue
            
            raw_start = row['start_date'].strip()
            date, display = self._parse_date_field(raw_start)
            row['start_date'] = date
            row['start_date_display'] = display

            if row.get('end_date'):
                raw_end = row['end_date'].strip()
                date, display = self._parse_date_field(raw_end)
                row['end_date'] = date
                row['end_date_display'] = display
            else:
                row['end_date'] = None
                row['end_date_display'] = None
                 
            results.append(row)
        return results

    def create_record(self, data: Dict[str, Any]):
        location = None
        if data.get('location'):
            location, _ = Location.objects.get_or_create(name=data['location'].strip())

        people = []
        if data.get('people'):
            names = [t.strip() for t in data['people'].split(',') if t.strip()]
            for name in names:
                person, _ = Person.objects.get_or_create(name=name)
                people.append(person)

        timelines = self._get_or_create_timelines(data.get('timelines', ''))
        sources = self._get_or_create_sources(data.get('sources', ''))

        event = TimelineEvent.objects.create(
            title=data.get('title'),
            description=data.get('description', ''),
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            location=location,
            link=data.get('link', ''),
            owner=self.user if self.user and self.user.is_authenticated else None
        )
        
        if people:
            event.people.set(people)
        if timelines:
            event.timelines.set(timelines)
        if sources:
            event.description_sources.set(sources)
        
        return event

class PersonImporter(BaseImporter):
    """
    Importer for People CSV.
    Headers: name, description, birth_date, death_date, timelines, link, sources
    Supports BCE dates: e.g. "44 BCE", "44 BC"
    """
    def parse(self, file_obj) -> List[Dict[str, Any]]:
        if isinstance(file_obj, bytes):
            file_obj = io.StringIO(file_obj.decode('utf-8'))
        elif hasattr(file_obj, 'read'):
             content = file_obj.read().decode('utf-8')
             file_obj = io.StringIO(content)

        reader = csv.DictReader(file_obj)
        results = []
        for row in reader:
            if not row.get('name'):
                continue
            
            if row.get('birth_date'):
                date, display = self._parse_date_field(row['birth_date'].strip())
                row['birth_date'] = date
                row['birth_date_display'] = display
            else:
                row['birth_date_display'] = None
                        
            if row.get('death_date'):
                date, display = self._parse_date_field(row['death_date'].strip())
                row['death_date'] = date
                row['death_date_display'] = display
            else:
                row['death_date_display'] = None
                    
            results.append(row)
        return results

    def create_record(self, data: Dict[str, Any]):
        timelines = self._get_or_create_timelines(data.get('timelines', ''))
        sources = self._get_or_create_sources(data.get('sources', ''))

        person, created = Person.objects.get_or_create(name=data['name'].strip())
        
        if data.get('description'):
            person.description = data.get('description')
        if data.get('birth_date'):
            person.birth_date = data.get('birth_date')
        if data.get('death_date'):
            person.death_date = data.get('death_date')
        if data.get('link'):
            person.link = data.get('link')

        if not person.owner and self.user and self.user.is_authenticated:
            person.owner = self.user

        person.save()

        # Assuming person model has timelines (it doesn't directly, events do, but we could add people to timelines?).
        # Wait, models.py: Timeline has events. Timeline tracking for Person isn't direct.
        # Typically People are mapped via TimelineEvents.
        # For now we'll ignore timelines for people unless we create dummy events. We'll skip timelines for Person.
        
        if sources:
            person.description_sources.set(sources)
            
        return person

class LocationImporter(BaseImporter):
    """
    Importer for Locations CSV.
    Headers: name, description, coordinates, link, sources
    """
    def parse(self, file_obj) -> List[Dict[str, Any]]:
        if isinstance(file_obj, bytes):
            file_obj = io.StringIO(file_obj.decode('utf-8'))
        elif hasattr(file_obj, 'read'):
             content = file_obj.read().decode('utf-8')
             file_obj = io.StringIO(content)

        reader = csv.DictReader(file_obj)
        results = []
        for row in reader:
            if not row.get('name'):
                continue
            results.append(row)
        return results

    def create_record(self, data: Dict[str, Any]):
        sources = self._get_or_create_sources(data.get('sources', ''))

        location, created = Location.objects.get_or_create(name=data['name'].strip())
        
        if data.get('description'):
            location.description = data.get('description')
        if data.get('coordinates'):
            location.coordinates = data.get('coordinates')

        if not location.owner and self.user and self.user.is_authenticated:
            location.owner = self.user

        location.save()

        if sources:
            location.description_sources.set(sources)
            
        return location
