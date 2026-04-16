from django.core.management.base import BaseCommand
from timeline.models import HelpTopic, HelpCategory, HelpImage

class Command(BaseCommand):
    help = 'Loads/Updates all application help content and documentation'

    def handle(self, *args, **options):
        self.stdout.write("Loading help categories and topics...")
        
        # 1. Define Categories
        getting_started, _ = HelpCategory.objects.get_or_create(name='Getting Started', defaults={'order': 10})
        data_management, _ = HelpCategory.objects.get_or_create(name='Data Management', defaults={'order': 20})
        advanced_features, _ = HelpCategory.objects.get_or_create(name='Advanced Features', defaults={'order': 30})

        # 2. Define Topics
        self.load_intro(getting_started)
        self.load_graph(advanced_features)
        self.load_advanced_topics(advanced_features)
        self.load_sources(advanced_features)
        self.load_events(data_management)
        self.load_people(data_management)
        self.load_locations(data_management)
        self.load_cloning(advanced_features)
        self.load_stories(advanced_features)
        self.load_permissions(advanced_features)
        self.load_research_dashboard(advanced_features)
        
        self.stdout.write(self.style.SUCCESS("Help content successfully loaded/updated."))

    def load_intro(self, category):
        content = """# Introduction to TimeWrit
Welcome to **TimeWrit**, a powerful platform designed for historical research, genealogy, and chronological storytelling.

## The Interface at a Glance
When you first open TimeWrit, you are presented with a dynamic, interactive workspace.

![Main Interface Overview](/media/help_images/main_interface_overview.png)

### 1. Navigation & Display Controls
- **Zoom (+/-)**: Adjust the chronological scale of the timeline.
- **FIT**: Automatically adjust the view to encompass all currently filtered events.
- **PLAY**: Animate the progression of events through time.
- **COMPARE**: Toggle the comparison view to analyze two timelines side-by-side.
- **MAP**: View your events on an interactive geographical map.
- **CHART (Graph)**: Switch to the non-linear relationship view.

> [!NOTE]
> For a deep dive into visualizing your project's data as a network, see [The Knowledge Graph](/help/knowledge-graph/).
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='intro',
            defaults={
                'title': 'Introduction to TimeWrit',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 1
            }
        )
        self.add_images(topic, [
            ('Main Interface Overview', 'help_images/main_interface_overview.png'),
            ('Navigation Controls', 'help_images/navigation_controls_focused.png')
        ])

    def load_graph(self, category):
        content = """While the Timeline shows *when* things happened, the **Knowledge Graph** shows *how* they are connected. 

![Knowledge Graph Overview](/media/help_images/graph_view_overview.png)

## Interactive Discovery
- **Click and Drag**: Move nodes around to organize your mental model.
- **Click**: Open the full details of any person, event, or location in the side panel.

## Understanding the Nodes
- **Green (Person Icon)**: Represents individuals and their social connections.
- **Blue (Solid Dot)**: Represents **Events**.
- **Orange (Map Pin)**: Represents **Locations**.
- **Dark Grey (Document Icon)**: Represents **Sources**.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='knowledge-graph',
            defaults={
                'title': 'The Knowledge Graph',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 10
            }
        )
        self.add_images(topic, [('Knowledge Graph Overview', 'help_images/graph_view_overview.png')])

    def load_advanced_topics(self, category):
        content = """Once you are comfortable with basic navigation, TimeWrit offers specialized tools for deep correlation.

## Grouping Mode
The **Grouping** dropdown segments your timeline into horizontal "swim lanes" based on common attributes like **Timeline**, **Person**, or **Story**.

## Compare Mode
**Compare Mode** allows you to render two independent data sets side-by-side on split screens.

![Compare Mode](/media/help_images/compare_mode_split.png)

## Playback Mode
Click the **PLAY** button to activate animated discovery. The events will appear and vanish on the map in real-time as the scrubber moves.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='advanced-topics',
            defaults={
                'title': 'Advanced Interface Topics',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 30
            }
        )
        self.add_images(topic, [
            ('Compare Mode', 'help_images/compare_mode_split.png'),
            ('Playback Controls', 'help_images/playback_controls.png')
        ])

    def load_sources(self, category):
        content = """TimeWrit is a tool for historical evidence. Every date and location can be backed by a primary or secondary source.

## The Citation Library
Access the central repository by clicking **Bibliography** in the main header.

![Citation Library](/media/help_images/citation_library_view.png)

## Citing Evidence
Citations are displayed as numerical superscripts (e.g., `[1]`) next to the specific field they support. The system automatically numbers citations and generates a full list at the bottom of every detail card.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='sources',
            defaults={
                'title': 'Sources & Bibliography',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 40
            }
        )
        self.add_images(topic, [('Citation Library View', 'help_images/citation_library_view.png')])

    def load_events(self, category):
        content = """Events are the foundation of your timeline, representing specific moments or spans of time.

## Filling the Form
The event form captures complex research data while maintaining academic integrity.

![Event Form Top](/media/help_images/event_admin_form_top.png)

### Flexible Chronology
- **Date Precision**: Choose between *Exact*, *Circa (c.)*, *Before*, or *After*.
- **Date Granularity**: Controls the display format (Year, Month, or Day).

### Mapping Connections
Link individuals, primary locations, and narratives to each event to weave a cohesive social network.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='adding-editing-events',
            defaults={
                'title': 'Adding & Editing Events',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 10
            }
        )
        self.add_images(topic, [('Event Form Top', 'help_images/event_admin_form_top.png')])

    def load_people(self, category):
        content = """Manage the individuals in your project. Track their life spans, relationships, and involvement in events.
- **Biographical Data**: Birth dates, death dates, and locations.
- **Relationships**: Link parents, children, and spouses to build family trees.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='people',
            defaults={
                'title': 'Managing People',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 20
            }
        )

    def load_locations(self, category):
        content = """Geographical entities serve as the anchor for your events.
- **Aliases**: Record multiple historical names for the same location.
- **Hierarchy**: Nest locations (e.g., *City* inside *State*).
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='locations',
            defaults={
                'title': 'Geographical Locations',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 30
            }
        )

    def load_cloning(self, category):
        content = """Copy existing entities (Events, People, Locations) into new ones to speed up data entry for similar records.
Use the **CLONE** button in the administration forms.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='cloning',
            defaults={
                'title': 'Cloning Entities',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 50
            }
        )

    def load_stories(self, category):
        content = """Weave events into linear narratives using the **Storytelling** module.
- **Sequencing**: Define the order of events within a specific story.
- **Thematic Colors**: Tag stories with colors for visual distinction on the timeline.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='storytelling',
            defaults={
                'title': 'Chronological Storytelling',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 60
            }
        )

    def load_permissions(self, category):
        content = """Manage record ownership and collaborator access.
- **Private Flags**: Mark sensitive research data as internal-only.
- **Owner Consistency**: Ensure your team has the correct permissions to edit imported data.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='permissions',
            defaults={
                'title': 'Permissions & Ownership',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 70
            }
        )

    def load_research_dashboard(self, category):
        content = """The **Research Dashboard** is a centralized Kanban board designed to help you manage investigative tasks across your entire project. Instead of jumping between individual people or locations, you can see every open question in one unified view.

## Accessing the Dashboard
You can find the Dashboard in the main **Admin sidebar** under the "🎯 Research Dashboard" link. Access is restricted to users with the **Researcher** role or Superusers.

![Research Dashboard Overview](/media/help_images/research_dashboard_overview.png)

## The Kanban Board
Tasks are organized into three primary statuses:

- **Open Questions**: Your active to-do list. New questions appear here by default.
- **Deferred**: Use this for questions that require information you don't have yet. It keeps them visible but separated from your immediate priorities.
- **Answered**: Once a mystery is solved, it moves here for historical record.

## Understanding Priorities
Every task carries a color-coded priority level that determines its visual prominence and sorting order:

![Priority Card Detail](/media/help_images/research_card_detail.png)

- **High (Red)**: Critical investigative threads. These automatically float to the top of the "Open" column.
- **Medium (Amber)**: Standard research tasks.
- **Low (Grey)**: Background research or minor details.

## Quick Actions
To maintain research momentum, the dashboard includes **Quick Action** buttons:
- **Resolve**: Instantly marks a task as "Answered".
- **Defer**: Moves the task to the secondary column.
- **Re-open**: Available in the Deferred/Answered columns to bring a task back to "Open" status.
- **Edit**: Opens the full record for detailed answer entry.

> [!TIP]
> Click the entity name (e.g., "John Henry (Doc) Holliday") at the top of any card to jump directly to that entity's full administration page.
"""
        topic, _ = HelpTopic.objects.update_or_create(
            slug='research-dashboard',
            defaults={
                'title': 'The Research Dashboard',
                'category': category,
                'content': content,
                'is_published': True,
                'order': 80
            }
        )
        self.add_images(topic, [
            ('Research Dashboard Overview', 'help_images/research_dashboard_overview.png'),
            ('Priority Card Detail', 'help_images/research_card_detail.png')
        ])

    def add_images(self, topic, image_list):
        for caption, path in image_list:
            HelpImage.objects.update_or_create(
                topic=topic,
                caption=caption,
                defaults={'image': path}
            )
