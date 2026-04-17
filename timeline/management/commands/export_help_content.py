import os
import json
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings
from timeline.models import HelpTopic, HelpCategory, HelpImage

class Command(BaseCommand):
    help = 'Exports help content (categories, topics, images) to the repo assets'

    def handle(self, *args, **options):
        assets_dir = os.path.join(settings.BASE_DIR, 'timeline', 'help_assets')
        images_dest_dir = os.path.join(assets_dir, 'images')
        
        os.makedirs(images_dest_dir, exist_ok=True)
        
        data = {
            'categories': [],
            'topics': []
        }
        
        # Build Categories
        self.stdout.write("Exporting categories...")
        for cat in HelpCategory.objects.all():
            data['categories'].append({
                'name': cat.name,
                'order': cat.order
            })
            
        # Build Topics and Images
        self.stdout.write("Exporting topics and images...")
        for topic in HelpTopic.objects.all():
            topic_data = {
                'title': topic.title,
                'slug': topic.slug,
                'category_name': topic.category.name,
                'content': topic.content,
                'order': topic.order,
                'is_published': topic.is_published,
                'images': []
            }
            
            for img in topic.images.all():
                if img.image:
                    # Get the filename from the ImageField (this is the relative path from media root)
                    # e.g. help_images/main_interface_overview.png
                    filename = os.path.basename(img.image.name)
                    
                    try:
                        src_path = img.image.path
                        dest_path = os.path.join(images_dest_dir, filename)
                        
                        if os.path.exists(src_path):
                            shutil.copy2(src_path, dest_path)
                            self.stdout.write(f"  Copied image: {filename}")
                            
                            topic_data['images'].append({
                                'filename': filename,
                                'caption': img.caption
                            })
                        else:
                            self.stdout.write(self.style.WARNING(f"  Image MISSING at {src_path}"))
                    except NotImplementedError:
                        # Happens if using GCS storage locally (rare but possible)
                        self.stdout.write(self.style.WARNING(f"  Could not access local path for {img.image.name} - storage backend does not support .path"))

            data['topics'].append(topic_data)
            
        # Write JSON
        json_path = os.path.join(assets_dir, 'help_data.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        self.stdout.write(self.style.SUCCESS(f"\nFinalized: Exported {len(data['topics'])} topics and {len(data['categories'])} categories to {json_path}"))
