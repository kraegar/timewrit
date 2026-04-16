# TimeWrit - *Think 4th dimensionally*

TimeWrit is a highly sophisticated, open-source historical research and visualization tool. It helps researchers, genealogists, and hobbyists meticulously track events, people, places, and narrative threads across time.

![TimeWrit Interface](https://via.placeholder.com/1200x600?text=TimeWrit+Preview)

## Features
*   **Multi-View Layouts**: Switch fluidly between an interactive Timeline, a Geographic Map, an Entity Network Graph, and a Narrative Reading View.
*   **Complex Family Trees**: Built-in Mermaid.js generation handles complex polygamy and lineage scenarios.
*   **Academic Rigor (Disputed Facts)**: Don't guess. Features deep integration for tracking `disputed_facts` alongside strict citation management.
*   **Multi-Lane Comparison**: Easily spot contemporaneous events across different historical threads using timeline overlapping visual algorithms.
*   **Offline/Export Capabilities**: One-click exports to PDF, GEDCOM, JSON, and Markdown.

## Installation (Local Development)
TimeWrit is built on Python 3 and Django with a unified Tailwind CSS and Vanilla JS frontend.

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/timewrit.git
cd timewrit

# 2. Set up a virtual environment
python -m venv .venv
source .venv/bin/activate  # Or `.venv\Scripts\activate` on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env

# 5. Run migrations & create admin
python manage.py migrate
python manage.py createsuperuser

# 6. Start the server
python manage.py runserver
```

## Hybrid Architecture (Local vs. Cloud)
TimeWrit is built with a "Hybrid Architecture." It runs with zero configuration on a local machine (using SQLite and local files) but can be upgraded to an enterprise-grade cloud deployment by simply toggling environment variables.

| Feature | Local (Default) | Cloud/Enterprise (Opt-in) | Toggle Variable |
| :--- | :--- | :--- | :--- |
| **Database** | SQLite | PostgreSQL (Cloud SQL) | `DATABASE_URL` |
| **Auth** | Django Login | Identity-Aware Proxy (IAP) | `USE_IAP` |
| **Storage** | Local Disk | Cloud Storage (GCS) | `USE_GCS` |
| **Caching** | LocMemCache | Redis (Memorystore) | `USE_REDIS` |
| **Logging** | Console (Stdout) | Cloud Monitoring | `USE_CLOUD_LOGGING` |
| **Secrets** | `.env` file | Cloud Secret Manager | `USE_SECRET_MANAGER` |

### Cloud Deployment Fast-Track
To enable cloud features, simply add the corresponding flags to your `.env` file (see `.env.example` for details). For example, to enable IAP and GCS Storage:
```bash
USE_IAP=True
USE_GCS=True
GS_BUCKET_NAME=your-bucket-name
```

## Usage
Head to `http://localhost:8000/admin/` to begin populating data. Add *Locations*, *People*, and *Events*. Create *Timelines* to group events logically. Click "View Site" to explore your generated 4-dimensional web!

## License
Licensed under the MIT License.
