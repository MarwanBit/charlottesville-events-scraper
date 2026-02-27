# Charlottesville Events Scraper

A production-style web scraper that collects event data from  
https://www.visitcharlottesville.org/events/  
and stores structured event information in PostgreSQL, with Excel export and dashboard visualization.

---

## 🚀 Project Overview

This project is a modular, testable web scraping system designed with clean architecture principles.

It:

- Crawls paginated event listings
- Extracts structured event data
- Normalizes and categorizes events
- Stores them in PostgreSQL
- Exports results to Excel
- Provides a Streamlit dashboard for visualization
- Includes unit and integration tests

The architecture emphasizes separation of concerns and testability.

---

## 🏗 Architecture

The scraper is organized into independent layers:

# Charlottesville Events Scraper

A production-style web scraper that collects event data from  
https://www.visitcharlottesville.org/events/  
and stores structured event information in PostgreSQL, with Excel export and dashboard visualization.

---

## 🚀 Project Overview

This project is a modular, testable web scraping system designed with clean architecture principles.

It:

- Crawls paginated event listings
- Extracts structured event data
- Normalizes and categorizes events
- Stores them in PostgreSQL
- Exports results to Excel
- Provides a Streamlit dashboard for visualization
- Includes unit and integration tests

The architecture emphasizes separation of concerns and testability.

---

## 🏗 Architecture

The scraper is organized into independent layers:

client.py → HTTP session management
crawler.py → Pagination logic
listing_parser.py → Extracts event cards
detail_scraper.py → Extracts event detail page data
transformer.py → Categorization & feature engineering
repository.py → Database interaction (PostgreSQL)
excel_exporter.py → Excel export
pipeline.py → Orchestrates entire workflow
cli.py → Entry point

---

## 🧠 Features

- Pagination-aware crawling
- Early stop detection
- JSON-LD structured data parsing
- Keyword-based categorization
- Date/time feature engineering
- Idempotent database upsert
- Processed URL tracking
- Dockerized PostgreSQL
- Unit + integration testing
- Streamlit dashboard

---

## 🛠 Tech Stack

- Python 3.12
- BeautifulSoup4
- Requests
- SQLAlchemy
- PostgreSQL (Docker)
- OpenPyXL
- Streamlit
- Pytest

---

## 📂 Project Structure

src/app/
cli.py
pipeline.py
crawler.py
client.py
listing_parser.py
detail_scraper.py
transformer.py
repository.py
excel_exporter.py
models.py
tests/
unit/
integration/
fixtures/
docker-compose.yml
README.md

---

## 🐳 Database Setup (Docker)

Start PostgreSQL:

```bash
docker compose up -d
```

Database credentials: `POSTGRES_DB=events`, `POSTGRES_USER=events`, `POSTGRES_PASSWORD=events`.

**Run a headed browser in Docker and view the Xvfb display via VNC**

1. Rebuild and start the stack, then run the pipeline with the script that starts Xvfb + VNC:

```bash
docker compose build app
docker compose up -d
docker exec -it charlottesville_app bash /app/scripts/run-headed-vnc.sh
```

2. **Connect to the VNC screen from your machine (not from inside Docker):**

   Run your VNC client **on your host** (your Mac, Windows, or Linux PC). Docker Compose maps the container’s port 5900 to your host’s port 5900 (`5900:5900` in `docker-compose.yml`), so connecting to **localhost** on your host reaches the VNC server running inside the container.

   - **Address:** `localhost` or `127.0.0.1` (this is your computer; Docker forwards it to the container)
   - **Port:** `5900`
   - **Password:** none (leave blank)

   **If Docker is running on another machine** (e.g. a remote server or VM): run the VNC client on your laptop and connect to that machine’s IP or hostname, port 5900 (e.g. `vnc://myserver.example.com:5900`). Ensure port 5900 is open in the firewall/security group.

   **VNC client options:**

   - **macOS:** [RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/) or [TigerVNC](https://tigervnc.org/) — connect to `127.0.0.1` (or `localhost`), port `5900`. Built-in Screen Sharing often fails with standard VNC from Docker; use a dedicated VNC client instead.
   - **Windows:** [TigerVNC Viewer](https://tigervnc.org/), [RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/), or built-in Remote Desktop with a VNC plugin.
   - **Linux:** `vinagre`, `remmina`, or `vncviewer` (e.g. `vncviewer localhost:5900`).

   **If connection fails (e.g. “unable to connect” on macOS):**

   1. Confirm the VNC script is running (`docker exec … run-headed-vnc.sh`) and that you see “VNC server on port 5900” in the output.
   2. From the host, check that port 5900 is open: `nc -zv 127.0.0.1 5900` (should say “succeeded”).
   3. Use **RealVNC Viewer** or **TigerVNC** instead of macOS Screen Sharing; Screen Sharing can be unreliable with Docker-forwarded VNC.
   4. In the client, use address `127.0.0.1` and port `5900` (some clients use “127.0.0.1:5900” or a separate port field).
   5. If the first screen takes 4+ minutes and seems stuck, disconnect the VNC client, stop the script (Ctrl+C in the `docker exec` terminal), remove the X lock (`docker exec charlottesville_app rm -f /tmp/.X99-lock`), then run the script again. The script now uses a smaller, lower-depth display so the first frame should finish in under a minute.

   Once connected, you’ll see the virtual desktop and the Chrome window when the pipeline uses the browser. Use this to debug when the browser seems stuck.

---

▶️ Run Scraper
source .venv/bin/activate
PYTHONPATH=src python -m app.cli
📊 Run Dashboard
PYTHONPATH=src streamlit run src/app/dashboard.py
🧪 Run Tests
PYTHONPATH=src pytest
🗄 Reset Database
docker exec -it charlottesville_db \
psql -U events -d events \
-c "TRUNCATE processed_urls, event_records RESTART IDENTITY CASCADE;"
🔎 Design Decisions
Separation of scraping, transformation, and persistence layers
Idempotent scraping using processed URL tracking
Database upsert logic to avoid duplicates
Fixture-based parser testing for stability
Early stop detection based on repeated pagination
Explicit pipeline orchestration for maintainability
📈 Future Improvements
Add retry logic with exponential backoff
Add structured logging
Add CI pipeline (GitHub Actions)
Add Dockerized scraper service
Add API endpoint for data access
Improve categorization using NLP
Author
Abra Pourseif

---

# Optional: Want It To Look Even More Professional?

We can also:

- Add a small architecture diagram (ASCII or Mermaid)
- Add badges (Python version, tests passing, Dockerized)
- Add “Why This Project Exists”
- Add performance metrics

