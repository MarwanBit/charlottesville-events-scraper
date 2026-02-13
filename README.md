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

Author 
Abra Pourseif

