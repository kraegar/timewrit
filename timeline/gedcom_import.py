import logging
from datetime import datetime
from django.db import transaction
from django.contrib.auth.models import User
from ged4py import GedcomReader
from ged4py.model import Individual, Record
from .models import Person, PersonRelationship, Location, Source, Tag

logger = logging.getLogger(__name__)

class GedcomImporter:
    def __init__(self, file_path, owner, timeline=None):
        self.owner = owner
        self.timeline = timeline
        
        # Pre-process the file to handle non-standard line breaks (like in Grevenstuk.ged)
        self.file_path = self._preprocess_file(file_path)
        self.reader = GedcomReader(self.file_path, encoding='utf-8')
        
        self.tag_gedcom, _ = Tag.objects.get_or_create(
            name="Imported via GEDCOM",
            defaults={"color": "#6B7280"}
        )
        # Internal mapping of GEDCOM XREFs to Django Model IDs
        self.indi_map = {}  # xref -> person_id
        self.sour_map = {}  # xref -> source_id
        self.loc_map = {}   # name -> location_id

    def _preprocess_file(self, file_path):
        """
        Fixes common GEDCOM syntax errors before parsing.
        e.g., lines that DON'T start with a level number (0-9).
        Handles UTF-8 BOM.
        """
        import tempfile
        import os
        
        needs_fixing = False
        with open(file_path, 'rb') as f:
            content = f.read()
            # Handle BOM
            try:
                decoded = content.decode('utf-8-sig')
            except:
                decoded = content.decode('latin-1', errors='ignore')
            
            for line in decoded.splitlines():
                line = line.strip()
                if line and not line[0].isdigit():
                    needs_fixing = True
                    break
        
        if not needs_fixing:
            return file_path

        logger.info(f"Pre-processing malformed GEDCOM: {file_path}")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ged_fixed', mode='w', encoding='utf-8')
        for line in decoded.splitlines():
            line_s = line.strip()
            if line_s and line_s[0].isdigit():
                tmp.write(line + '\n')
            elif line_s:
                print(f"DEBUG: Skipping malformed GEDCOM line: {repr(line_s)}")
        tmp.close()
        return tmp.name

    def close(self):
        """Explicitly close the reader to release file handles on Windows."""
        if self.reader and hasattr(self.reader, '_file'):
            try:
                self.reader._file.close()
            except:
                pass
        # If we created a pre-processed file, delete it
        if hasattr(self, 'file_path') and '.ged_fixed' in self.file_path:
            try:
                import os
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
            except:
                pass

    def _safe_value(self, val):
        """ged4py sometimes returns tuples (value, something) or strings."""
        if isinstance(val, tuple):
            # For names, it's (given, surname, suffix)
            return " ".join([v for v in val if v]).strip()
        return str(val) if val is not None else ""

    def _parse_date(self, date_str):
        """Minimal date parser for GEDCOM format."""
        if not date_str:
            return None, 'exact', 'day'
        
        # ged4py might have better date support, but for now we do simple string cleaning
        # and attempt to parse years at least.
        precision = 'exact'
        if 'ABT' in date_str or 'CIRCA' in date_str:
            precision = 'circa'
            date_str = date_str.replace('ABT', '').replace('CIRCA', '').strip()
        elif 'BEF' in date_str:
            precision = 'before'
            date_str = date_str.replace('BEF', '').strip()
        elif 'AFT' in date_str:
            precision = 'after'
            date_str = date_str.replace('AFT', '').strip()

        # Try to extract a year
        try:
            # Very naive: look for 4 digits
            import re
            match = re.search(r'\d{4}', date_str)
            if match:
                year = int(match.group())
                # For safety in our models which use DateField, we pick Jan 1st if only year is found
                return f"{year}-01-01", precision, 'year'
        except:
            pass
        
        return None, precision, 'day'

    def import_all(self):
        with transaction.atomic():
            self.import_sources()
            self.import_individuals()
            self.import_families()
        return len(self.indi_map)

    def import_sources(self):
        for rec in self.reader.records0("SOUR"):
            title = self._safe_value(rec.sub_tag_value("TITL")) or "Untitled Source"
            author = self._safe_value(rec.sub_tag_value("AUTH"))
            pub = self._safe_value(rec.sub_tag_value("PUBL"))
            
            source = Source.objects.create(
                title=title,
                author=author,
                publication_date=pub,
                owner=self.owner
            )
            source.tags.add(self.tag_gedcom)
            self.sour_map[rec.xref_id] = source.id

    def get_or_create_location(self, place_name):
        if not place_name:
            return None
        if place_name in self.loc_map:
            return Location.objects.get(id=self.loc_map[place_name])
        
        loc, _ = Location.objects.get_or_create(
            name=place_name,
            owner=self.owner,
            defaults={'status': 'unverified'}
        )
        if _: # if created
            loc.tags.add(self.tag_gedcom)
        self.loc_map[place_name] = loc.id
        return loc

    def import_individuals(self):
        for rec in self.reader.records0("INDI"):
            name_rec = rec.sub_tag("NAME")
            name = "Unknown"
            if name_rec:
                name = self._safe_value(name_rec.value).replace("/", "").strip()
            
            # Birth
            birt = rec.sub_tag("BIRT")
            b_date, b_prec, b_gran = (None, 'exact', 'day')
            b_loc = None
            if birt:
                b_date, b_prec, b_gran = self._parse_date(self._safe_value(birt.sub_tag_value("DATE")))
                b_loc = self.get_or_create_location(self._safe_value(birt.sub_tag_value("PLAC")))

            # Death
            deat = rec.sub_tag("DEAT")
            d_date, d_prec, d_gran = (None, 'exact', 'day')
            d_loc = None
            if deat:
                d_date, d_prec, d_gran = self._parse_date(self._safe_value(deat.sub_tag_value("DATE")))
                d_loc = self.get_or_create_location(self._safe_value(deat.sub_tag_value("PLAC")))

            # Gender
            sex = self._safe_value(rec.sub_tag_value("SEX")).upper()
            gender = 'unknown'
            if sex == 'M': gender = 'male'
            elif sex == 'F': gender = 'female'
            elif sex == 'X': gender = 'intersex'
            elif sex == 'U': gender = 'unknown'

            person = Person.objects.create(
                name=name,
                owner=self.owner,
                birth_date=b_date,
                birth_date_precision=b_prec,
                birth_date_granularity=b_gran,
                birth_location=b_loc,
                death_date=d_date,
                death_date_precision=d_prec,
                death_date_granularity=d_gran,
                death_location=d_loc,
                gender=gender,
                status='unverified'
            )
            person.tags.add(self.tag_gedcom)
            
            # Link SOURces
            for s_ref in rec.sub_tags("SOUR"):
                s_xref = self._safe_value(s_ref.value)
                source_id = self.sour_map.get(s_xref)
                if source_id:
                    person.description_sources.add(source_id)

            self.indi_map[rec.xref_id] = person.id

            # Link auto-generated birth/death events to the selected timeline
            if self.timeline:
                from .models import TimelineEvent
                events = TimelineEvent.objects.filter(
                    people=person,
                    is_auto_generated=True
                )
                for event in events:
                    event.timelines.add(self.timeline)

    def import_families(self):
        for rec in self.reader.records0("FAM"):
            husb_rec = rec.sub_tag("HUSB")
            wife_rec = rec.sub_tag("WIFE")
            
            husb_ref = husb_rec.xref_id if husb_rec else ""
            wife_ref = wife_rec.xref_id if wife_rec else ""
            
            children_refs = [c.xref_id for c in rec.sub_tags("CHIL") if c]
            
            h_id = self.indi_map.get(husb_ref)
            w_id = self.indi_map.get(wife_ref)
            
            # Spouse Relationship
            if h_id and w_id:
                PersonRelationship.objects.get_or_create(
                    from_person_id=h_id,
                    to_person_id=w_id,
                    relationship_type='spouse',
                    defaults={'notes': 'Imported from GEDCOM family record'}
                )

            # Parent-Child Relationships
            parents = [id for id in [h_id, w_id] if id]
            for child_ref in children_refs:
                c_id = self.indi_map.get(child_ref)
                if c_id:
                    for p_id in parents:
                        PersonRelationship.objects.get_or_create(
                            from_person_id=p_id,
                            to_person_id=c_id,
                            relationship_type='parent',
                            defaults={'notes': 'Imported from GEDCOM family record'}
                        )
