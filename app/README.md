# AI Curator (NYT + Economist → Instapaper)

Finds AI-related articles from NYT Article Search + The Economist RSS feeds, builds a daily digest, and (with your approval) saves them to Instapaper.

## Setup

```bash
git clone https://github.com/<your-username>/ai-curator.git
cd ai-curator
cp .env.example .env
nano .env   # add your NYT API key and Instapaper credentials
docker compose build
docker compose up -d
