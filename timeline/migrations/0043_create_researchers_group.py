from django.db import migrations

def create_researchers_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    # Create the Researchers group
    group, created = Group.objects.get_or_create(name='Researchers')

    # Define the models we want to grant full access to
    models_to_grant = [
        'location', 'person', 'source', 'tag', 'attachment', 
        'story', 'storyevent', 'timeline', 'timelineevent', 
        'eventimage', 'personrelationship', 'disputedfact', 
        'publiccomment', 'researchquestion'
    ]

    # Find the permissions specifically for our app
    # We use a filter to find all relevant perms (add, change, delete, view)
    permissions = Permission.objects.filter(
        content_type__app_label='timeline',
        codename__regex=r'^(add|change|delete|view)_'
    )

    # Add permissions to the group
    for perm in permissions:
        group.permissions.add(perm)

def remove_researchers_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Researchers').delete()

class Migration(migrations.Migration):

    dependencies = [
        ('timeline', '0042_researchquestion_priority'),
    ]

    operations = [
        migrations.RunPython(create_researchers_group, remove_researchers_group),
    ]
