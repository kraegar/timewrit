import os
import json
from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
from timeline.models import HelpTopic, HelpCategory, HelpImage

class Command(BaseCommand):
    help = 'Loads/Updates application help content from repo assets'

    def handle(self, *args, **options):
        assets_dir = os.path.join(settings.BASE_DIR, 'timeline', 'help_assets')
        json_path = os.path.join(assets_dir, 'help_data.json')
        
        if not os.path.exists(json_path):
            self.stdout.write(self.style.ERROR(f"Help data file not found at {json_path}. Run export_help_content first on a source machine."))
            return

        self.stdout.write("Loading help data from assets...")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 1. Sync Categories
        category_map = {}
        for cat_data in data.get('categories', []):
            cat, created = HelpCategory.objects.update_or_create(
                name=cat_data['name'],
                defaults={'order': cat_data['order']}
            )
            category_map[cat.name] = cat
            if created:
                self.stdout.write(f"Created category: {cat.name}")
            else:
                self.stdout.write(f"Updated category: {cat.name}")

        # 2. Sync Topics
        for topic_data in data.get('topics', []):
            category = category_map.get(topic_data['category_name'])
            if not category:
                self.stdout.write(self.style.WARNING(f"Category {topic_data['category_name']} not found for topic {topic_data['title']}. Skipping."))
                continue

            topic, created = HelpTopic.objects.update_or_create(
                slug=topic_data['slug'],
                defaults={
                    'title': topic_data['title'],
                    'category': category,
                    'content': topic_data['content'],
                    'order': topic_data['order'],
                    'is_published': topic_data['is_published']
                }
            )
            
            if created:
                self.stdout.write(f"Created topic: {topic.title}")
            else:
                self.stdout.write(f"Updated topic: {topic.title}")

            # 3. Sync Images
            # We clear existing images for this topic to ensure sync accurately matches the factory assets.
            topic.images.all().delete()
            
            for img_data in topic_data.get('images', []):
                img_filename = img_data['filename']
                asset_img_path = os.path.join(assets_dir, 'images', img_filename)
                
                if os.path.exists(asset_img_path):
                    with open(asset_img_path, 'rb') as f:
                        help_img = HelpImage(topic=topic, caption=img_data['caption'])
                        # This save() call copies the file from our repo assets to the 
                        # configured storage (media folder or GCS) seamlessly.
                        help_img.image.save(img_filename, File(f), save=True)
                        self.stdout.write(f"  Restored image: {img_filename}")
                else:
                    self.stdout.write(self.style.WARNING(f"  Asset image MISSING: {asset_img_path}"))

        self.stdout.write(self.style.SUCCESS("\nHelp content successfully synchronized from assets."))
