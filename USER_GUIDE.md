# LeadForge — User Guide

A simple guide to using LeadForge to find new clients. **No coding needed** — you
just type a few commands and open a spreadsheet.

---

## 1. What this tool does

LeadForge searches public LinkedIn posts for people who are **actively looking to
hire a marketing agency, freelancer, or consultant** — posts like *"looking for a
marketing agency to help with our launch"* or *"can anyone recommend a social
media agency?"*

It automatically:
- Finds those posts across the services you offer,
- Filters out the junk (job ads, recruiters, competitors, general chit-chat),
- Ranks the real leads by how fresh and how relevant they are,
- Gives you a clean Excel sheet with clickable links to each post.

You then open the sheet, click a link, and reach out on LinkedIn. That's it.

---

## 2. One-time setup

You only do this **once** on the computer that will run the tool.

### Step 1 — Install Python
Download Python 3.11 or newer from [python.org](https://www.python.org/downloads/)
and install it. During install, tick **"Add Python to PATH"**.

### Step 2 — Get the project
Put the project folder on the computer (from GitHub or a copy). Open a terminal
(PowerShell on Windows) **inside that folder**.

### Step 3 — Set it up
Type these one at a time and press Enter after each:

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

### Step 4 — Get a free search key
The tool uses a free service called **Serper** to search the web.
1. Go to [serper.dev](https://serper.dev) and sign up (free, no credit card).
2. Copy your API key from the dashboard.

### Step 5 — Add your key
1. Make a copy of the file `.env.example` and name the copy `.env`.
2. Open `.env` in Notepad and add these two lines at the bottom:
   ```
   SERPER_API_KEY=paste-your-key-here
   SEARCH_ENGINE=serper
   ```
3. Save.

### Step 6 — Finish setup
```
leadforge init
leadforge doctor
```
If `doctor` shows all green, you're ready. ✅

---

## 3. Everyday use — the 3-step routine

Every time you want fresh leads, do these three steps. (Make sure the terminal
shows `(.venv)` at the start of the line — if not, type `.venv\Scripts\activate`
first.)

### Step 1 — Find leads
```
leadforge intent scrape-all --since 7d
```
This searches for people asking for **all** your services (from `needs.yaml`),
posted in the last 7 days. **This takes a while** (there are deliberate pauses so
LinkedIn doesn't block you) — let it run. Change `7d` to `3d` for the last 3 days,
`30d` for a month.

### Step 2 — Rank them
```
leadforge intent score
```
This filters out the junk and ranks the real client leads from best to worst.

### Step 3 — Get your spreadsheet
```
leadforge intent export --format xlsx --max-age 7
```
This creates an Excel file in the **`exports`** folder with your client leads from
the last 7 days, best ones first.

Open that file, and start reaching out!

> 💡 To just peek at the leads in the terminal without making a file:
> `leadforge intent list`

---

## 4. Set which services you sell

Open the file **`needs.yaml`** and edit the list to match what your agency
offers. Use "provider" wording that fits "looking for a ___":

```
- marketing agency
- social media manager
- SEO agency
- Google Ads expert
- content creator
```

Add or remove lines anytime. The more services you list, the more (and the longer)
each search takes.

---

## 5. Reading your Excel sheet

| Column | What it means |
| --- | --- |
| **author_name** | Who posted (the potential client). |
| **lead_score** | 0–100, how promising the lead is. Higher = better. The sheet is sorted by this. |
| **category** | Always `client_lead` in your export — a real potential customer. |
| **need_text** | What they actually wrote — read this to understand what they want. |
| **post_url** | Link to the LinkedIn post. **Click to open it** (see the note below). |
| **posted_at** | When they posted. Fresher is better. |

**Reaching out:** be logged into LinkedIn in your browser first, then click a
`post_url`. Comment on the post or message the author — reference what they asked
for. (If you're logged out, LinkedIn shows a sign-in page instead of the post —
that's normal, just log in.)

---

## 6. Handy variations

```
leadforge intent scrape --need "social media manager" --since 3d   # one service, last 3 days
leadforge intent list --max-age 3                                  # only leads from the last 3 days
leadforge intent export --format csv                               # export as CSV instead of Excel
```

---

## 7. Good to know

- **Quality over quantity.** You'll get a handful of *genuine* leads per run, not
  hundreds. Each one is a real person who asked for exactly what you sell — worth
  far more than a cold list.
- **Run it regularly.** Intent goes stale fast. Running it every day or two catches
  fresh posts before your competitors do.
- **Free limits.** The free Serper plan covers thousands of searches a month —
  plenty. If you ever run out, the tool will tell you.
- **Nothing to hide from.** The tool only reads *public* posts, never logs into
  LinkedIn, and pauses between requests to stay within the rules.

---

## 8. If something goes wrong

| Problem | Fix |
| --- | --- |
| `leadforge` not recognized | Type `.venv\Scripts\activate` first (you should see `(.venv)`). |
| A link shows a LinkedIn sign-in page | Log into LinkedIn in your browser, then click again. The link is fine. |
| Search returns 0 results | Normal for a narrow window — try a longer `--since` (e.g. `30d`) or different services in `needs.yaml`. |
| "API key" error | Check your `SERPER_API_KEY` line in `.env` — no quotes, no extra spaces. |
| Scrape seems frozen | It's the built-in pause between requests (8–15 seconds each), not frozen. Let it run. |
| Excel export fails | Close the file if you have an old export open in Excel, then try again. |

---

*For a technical map of how the code works, see `CLAUDE.md`.*
