from django.core.management.base import BaseCommand
from django.db import models
from django.contrib.auth.models import User
from timeline.models import (
    Timeline, TimelineEvent, Person, Location, 
    Source, Attachment, Story, DisputedFact, 
    ResearchQuestion
)
import os

class Command(BaseCommand):
    help = 'Cleans up test users and orphaned records (null owners)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate the cleanup without actually deleting records',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        target_usernames = [
            'user1', 'test_researcher', 'test_gedcom_user_small', 
            'test_gedcom_user_large', 'exporter_user', 'importer_user', 'test_staff'
        ]
        
        target_users = User.objects.filter(username__in=target_usernames)
        self.stdout.write(f"Targeting users: {[u.username for u in target_users]}")
        
        files_to_delete = []

        # 1. Collect file paths before deletion (including orphans)
        
        # Locations
        locations = Location.objects.filter(models.Q(owner__in=target_users) | models.Q(owner__isnull=True))
        for loc in locations:
            if loc.image:
                files_to_delete.append(loc.image.path)
                
        # People
        people = Person.objects.filter(models.Q(owner__in=target_users) | models.Q(owner__isnull=True))
        for p in people:
            if p.image:
                files_to_delete.append(p.image.path)
                
        # Events & EventImages
        events = TimelineEvent.objects.filter(models.Q(owner__in=target_users) | models.Q(owner__isnull=True))
        for e in events:
            if e.image:
                files_to_delete.append(e.image.path)
            # Supplemental images
            for ei in e.additional_images.all():
                if ei.image:
                    files_to_delete.append(ei.image.path)

        # Attachments
        attachments = Attachment.objects.filter(models.Q(owner__in=target_users) | models.Q(owner__isnull=True))
        for a in attachments:
            if a.file:
                files_to_delete.append(a.file.path)

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would delete {len(files_to_delete)} files and records for {target_users.count()} users."))
            return

        # 2. Delete database records
        self.stdout.write("Deleting ownerless records...")
        models_to_clean = [
            Timeline, TimelineEvent, Person, Location, Source, 
            Attachment, Story, DisputedFact, ResearchQuestion
        ]
        for model in models_to_clean:
            count, _ = model.objects.filter(owner__isnull=True).delete()
            if count > 0:
                self.stdout.write(f"  Deleted {count} ownerless {model.__name__} records.")

        # Delete the test users (cascading)
        user_count = target_users.count()
        if user_count > 0:
            self.stdout.write(f"Deleting {user_count} users and all associated data...")
            target_users.delete()

        # 3. Cleanup files on disk
        self.stdout.write(f"Cleaning up {len(files_to_delete)} potential media files...")
        deleted_count = 0
        for file_path in set(files_to_delete):
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    self.stderr.write(f"Error deleting file {file_path}: {e}")
        
        self.stdout.write(self.style.SUCCESS(f"Cleanup complete. {deleted_count} files removed from disk."))
