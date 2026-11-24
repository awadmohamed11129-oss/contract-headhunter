# do good talent: user guide

This guide explains how to install and use **do good talent**, step by step. It is written for the people who run the app day to day: recruiters, coordinators and reviewers. You don't need any technical background to follow it.

Each line like **[IMAGE x.x: …]** marks a screenshot of the part being described. Its number matches the screenshot file of the same name (IMAGE 3.9b is `IMAGE3.9b.png`). Lines marked _(Mac screenshot to come)_ are still to be taken.

---

## Contents

1. [Introduction](#1-introduction)
2. [Quick start](#2-quick-start)
3. [Individual modules (the app's pages)](#3-individual-modules-the-apps-pages)
4. [Input format](#4-input-format)
5. [General flow of the app](#5-general-flow-of-the-app)
6. [Export / Import](#6-export--import)
7. [Appendix A: Troubleshooting](#appendix-a-troubleshooting)
8. [Appendix B: Profession names](#appendix-b-profession-names)
9. [Appendix C: Glossary](#appendix-c-glossary)

---

## 1. Introduction

### What the app is for

Contract roles in Canada are often filled on a first-come, first-served basis, and checking postings against a whole list of contractors by hand is slow. **do good talent** does the first sort for you. You give it:

- **your list of contractors** (their professional profiles, and optionally their résumés), and
- **job postings** you have found (in a spreadsheet, as links, or typed in by hand).

The app then uses Google's **Gemini** AI to read each job and every available contractor, and suggests **who fits each job, and why**. You review each suggestion and decide: **Approve**, **Reject** or **Needs info**. After that you can track each approved candidate through outreach to the hiring company, up to **Hired**.

**The app only suggests. A person makes every decision.** It never contacts anyone, applies to jobs, or sends email.

**[IMAGE 1.1: The app's main window, open on Find matches, with the five pages in the menu]**

### What it does, in short

| Step | What happens |
|---|---|
| 1. Load contractors | You pick your contractor folder. New contractors are added, changed ones are updated, and their résumés are stored. |
| 2. Add jobs | You add a jobs spreadsheet (CSV), a text file of links or a pasted posting, or type a job in by hand. |
| 3. Find matches | Gemini reads each new job against every available contractor. It first screens everyone, then takes a closer look at the most promising few. |
| 4. Review | For each job you see up to 3 clear fits (or, if nobody clearly fits, the single closest candidate to check by hand), each with a one-line reason and the details behind it. |
| 5. Decide | You approve, reject (with a reason) or mark "needs info". Every decision is saved with your name. |
| 6. Follow up | For approved candidates you record where the application stands (outreached, in progress, rejected or ghosted, hired). |
| 7. Share or back up | You export the suggestions to a spreadsheet, or save a password-protected backup of all the app's data. |

### How the suggestions are made

- For each job, Gemini **screens every available contractor** and keeps the ones who fit or partly fit.
- It then **reviews that shortlist in depth**. For each candidate it gives a **score from 0 to 100**, a one-line **reason**, a table of **what they meet** (their skill or result next to the job requirement it meets), **what is missing**, and any **warnings**.
- Everything Gemini lists as evidence is **checked against the job and the profile**. Anything it says that can't be found there is left out, and the app tells you so.
- Answers are **saved**. A job already judged is not sent to Gemini again, so re-running costs nothing. When you add new contractors, only those new people are checked against existing open jobs.

### Privacy

- **Everything stays on your computer.** Contractor profiles, résumés, decisions and exports are stored in the app's own data folder.
- **Gemini never sees names or contact details.** Each contractor is sent as an anonymous card with professional information only: headline, summary, skills, achievements, industries, target titles, seniority, years of experience, weekly hours, rate expectation, languages, and city and province. Names are also removed from the text before it is sent.
- **Résumés are never sent to Gemini.** They are stored only so that you can read them.
- **The contact person and email on a job posting** are shown to you only. They are never sent to Gemini.
- **Exports contain personal information** (contractor names). Keep them within your team.

### What the app does not do

- It does **not** send emails or contact companies or contractors.
- It does **not** log in to any website.
- It does **not** make final decisions: every suggestion waits for a person.

---

## 2. Quick start

### 2.1 Download

Download the install file from the project's GitHub **Releases** page, under **Assets**:

- GitHub link: _(to be added)_

| Your computer | File to download |
|---|---|
| Mac (Intel) | `dogoodtalent-mac-intel.dmg` |
| Windows | `dogoodtalent-windows.zip` |

**[IMAGE 2.1: The GitHub Releases page, with the Assets list open showing the two install files]**

### 2.2 Install

#### Mac

1. Double-click **`dogoodtalent-mac-intel.dmg`**. A window opens showing **dogoodtalent** and an **Applications** folder.
2. Drag **dogoodtalent** onto **Applications**.
3. Close the window, then eject the "do good talent" disk in the Finder sidebar.

**[IMAGE 2.2: The Mac install window, dragging dogoodtalent onto Applications]** _(Mac screenshot to come)_

#### Windows

1. Right-click **`dogoodtalent-windows.zip`** and choose **Extract All…**. Pick a place you'll remember, such as your **Documents** folder.
2. Open the extracted **dogoodtalent** folder. **Keep every file in it together**: the app needs all of them.
3. Optional: right-click **dogoodtalent.exe** and choose **Send to › Desktop (create shortcut)**.

### 2.3 Allow the app to open (first time only)

do good talent is not registered ("signed") with Apple or Microsoft, so the first time you open it your computer asks you to confirm that you trust it. You only need to do this once.

#### Mac

1. Open **Applications** and double-click **dogoodtalent**. A message says it can't be opened, or that Apple can't check it. Click **Done** (or **OK**).

   **[IMAGE 2.3: The Mac message saying the app can't be opened]** _(Mac screenshot to come)_

2. Open **System Settings › Privacy & Security**. Scroll down to the message about **dogoodtalent** and click **Open Anyway**. Enter your Mac password if asked.

   **[IMAGE 2.4: System Settings › Privacy & Security, with the "Open Anyway" button]** _(Mac screenshot to come)_

3. Click **Open** in the next message. From now on, the app opens normally.

   **[IMAGE 2.5: The final confirmation message with the "Open" button]** _(Mac screenshot to come)_

**On older versions of macOS:** right-click **dogoodtalent** in Applications, choose **Open**, then click **Open** again in the message.

#### Windows

1. Double-click **dogoodtalent.exe**.
2. If a box says **"Windows protected your PC"**, click **More info**, then **Run anyway**.

**[IMAGE 2.6: The "Windows protected your PC" box, with the "More info" link]**

**[IMAGE 2.7: The same box after clicking More info, with the "Run anyway" button]**

The first start can take a few seconds.

### 2.4 Get a Gemini API key

The app uses Google's Gemini AI to read the jobs and profiles. Gemini needs a **key**: a long code that identifies your account. The free tier is enough.

1. In a web browser, go to **aistudio.google.com** and sign in with a Google account.
2. Click **Get API key**, then **Create API key**.
3. Copy the key (a long line of letters and numbers).

**[IMAGE 2.8: Google AI Studio, the API Keys page with the "Create API key" button]**

**[IMAGE 2.9: The new key's details in Google AI Studio, with the "Copy key" button (the key itself is hidden)]**

Good to know:

- **Stay on the free tier.** Don't turn on billing on Google's site.
- **The free tier has a daily allowance** of requests. It resets at **midnight Pacific time** (3 a.m. Eastern). The exact numbers are set by Google and can change. The app shows how much you have used today (see 3.1).
- **Treat the key like a password.** Don't email it or share it.

### 2.5 First-time settings in the app

1. Open the app and click **Settings** in the menu at the top right.
2. Under **Gemini key**, paste the key and click **Save key**. The card now says "A key is saved." The key is stored on this computer and is never shown again.
3. Under **Your name**, type your name and click **Save name**. Your name is saved with every decision you make.

**[IMAGE 2.10: The Settings page after saving the key: "A key is saved." and the "Key saved." message]**

You're ready. Continue with [5.1 First-time setup](#51-first-time-setup) for the full first run, or read section 3 to learn each page.

---

## 3. Individual modules (the app's pages)

The app has five pages. You move between them with the menu at the top right of every page:

| Menu item | What it's for |
|---|---|
| **Find matches** | Load contractors and jobs, then run the matching. |
| **Results** | Review Gemini's suggestions for each job and decide. |
| **Jobs** | See every job, its state, and track the approved candidates' applications. |
| **Talent** | See every contractor, switch their availability, and view or edit their profile and résumé. |
| **Settings** | Gemini key, your name, data folder, and backup (export and import). |

**[IMAGE 3.0: The header: the "do good talent" logo on the left, the five menu items on the right, with the current page highlighted]**

**Common to every page:**

- **The logo** ("do good talent", top left) takes you back to **Find matches**.
- **The current page** is highlighted in the menu with a white underline.
- **The run indicator:** while a run is going, a small spinning label appears in the header, on every page, such as "Matching… 45%" or "Ingesting… 20%". If the run is waiting for your answer about the Gemini quota, it says **"Answer needed on Find matches"**. Click it to go back to Find matches.
- **Messages** appear briefly at the bottom of the screen after an action: green for success, orange for a warning, red for an error.
- **Every deletion asks first.** A pop-up names what will be deleted. **Cancel** is the safe choice.

**[IMAGE 3.0b: The run indicator in the header while matching is in progress]**

---

### 3.1 Find matches

**What it's for:** This is where you bring contractors and jobs into the app and start the matching. It is the page the app opens on.

The full page is shown in IMAGE 1.1. The page has, from top to bottom:

#### a. The Gemini key reminder

If no Gemini key is saved yet, a pale yellow card at the top says **"Add your Gemini key in Settings before the first run."** Its **Open Settings** button takes you to Settings. The card disappears once a key is saved.

#### b. Step 1: Contractors (optional)

This card loads or updates your contractor list. **It is optional:** use it the first time, and whenever contractors are added or their details change. If your list hasn't changed, skip it.

| Element | What it does |
|---|---|
| **"N contractor(s) processed."** | How many contractors the app holds right now. |
| **Choose folder…** | Opens a folder picker. Pick your **contractor folder**: the folder that holds the contractor file and, optionally, a `resume` folder of PDFs. See [4.2 Contractors](#42-contractors) for the layout. |
| **The path beside the button** | Shows the folder you picked, or "Nothing picked yet". |
| **The summary line** | After picking, it shows what will be loaded, such as "contractors.csv: 24 contractor(s) · 18 résumé(s), stored when you click Ingest or Find matches." **Nothing is stored yet at this point.** |
| **"Skipped (not named by a talent ID): …"** (orange) | Lists PDFs in the résumé folder whose file name doesn't match any contractor's talent ID. Those résumés are not loaded. Rename them to the exact talent ID (for example `TAL-CAN-001.pdf`) and pick the folder again. |

If the folder has no contractor file, or more than one, a red message explains the problem and nothing is picked.

#### c. Step 2: Jobs

This card adds job postings. You can add several files, one after another, and also type jobs in by hand.

| Element | What it does |
|---|---|
| **Choose files…** | Opens a file picker. Pick one or more jobs files: a **jobs CSV** (`.csv`) or a **text file** (`.txt`). See [4.1 Jobs](#41-jobs) for the formats. You can pick more files afterwards: each is added to the list. |
| **"Added jobs.csv: 12 job(s)."** | Confirms each file picked and how many jobs (or links) it holds. |
| **"Not imported: Row 5: …"** (orange) | A row of a jobs CSV that can't be used, and why (for example a missing link or an unclear date). The other rows still go in. Fix the row in your file, then pick the file again. |
| **Add a job by hand** | Opens a form to type or paste one job (see below). |
| **Get CSV template** | Saves a blank-format jobs spreadsheet with two example rows (one English, one French). A save dialog asks where to put it. Use it as the starting point for your own jobs CSV. |
| **"Entered by hand (N), stored on the next Ingest or Find matches:"** | Lists jobs you entered with the form that are not stored yet, by title and company. The **✕** button next to each removes that entry (it asks first). |

Jobs already in the app are recognized by their link and **skipped**. To change a job that was already imported, close it and delete it on the **Jobs** page, then import it again.

##### The "Add a job by hand" form

The form has the same fields as the jobs CSV. Each field has a short hint under it. **Job posting link** and **Job title** are required (marked with a red \*).

| Field | What to enter |
|---|---|
| Job posting link | The posting's web address. The app uses it to recognize the same job if it comes in again. |
| Job title | As written in the posting, e.g. "Data Analyst (6-month contract)". |
| Company | The hiring company, or the agency if that's all the posting names. |
| Contact person | The HR or hiring contact's name, if the posting gives one. |
| Contact email | Where to reach them, e.g. jordan.lee@example.ca. |
| Location | City and province, e.g. Toronto, ON. |
| Work mode | Not stated, On-site, Hybrid or Remote. |
| Hours per week | A number, e.g. 40 or 37.5. 30 or more shows as full-time (FT), fewer as part-time (PT). |
| Pay | In Canadian dollars: a number, or a range (the lower end is kept), e.g. 90 or 85–95. |
| Pay type | Hourly, or Salary (per year). |
| Posted date | When the job was posted. Leave empty if unknown. |
| Responsibilities | One per line. What the person will do. |
| Qualifications | One per line. Required skills, experience, languages. |

Formatting copied from a web page (bullets, bold, extra spaces and empty lines) is removed automatically.

- **Save** saves the job and closes the form.
- **Save and add another** saves the job and clears the form for the next one.
- **Cancel** closes the form without saving.

If something is wrong (for example the link doesn't start with `http`), an orange message says what to fix, and the form stays open. A saved job appears under "Entered by hand" and is stored on the next **Ingest** or **Find matches**.

#### d. The two run buttons

| Button | What it does | Uses Gemini? |
|---|---|---|
| **Ingest** | **Stores** the picked contractors, résumés and jobs **without matching**. Use it to check that everything loaded correctly before you spend Gemini quota. When it's done, the line under the buttons summarizes it, e.g. "Ingested: 2 contractor(s) added, 1 updated · 3 résumé(s) stored · 12 job(s) imported. Nothing sent to Gemini." | No |
| **Find matches** | Stores whatever is picked (like Ingest), **then matches**. For every open job, it asks Gemini about each available contractor who hasn't been judged for that job yet. Jobs and contractors already judged are not asked again. | Yes |

While a run is going:

- Both buttons are greyed out.
- **The progress bar** and the stage label above it show which stage the run is at and how far along it is, as a percentage.
- **The status line** says what's happening. Matching can take a few minutes when there are new jobs.
- **The progress box** (the large box below) lists what has happened, in plain sentences. When matching ends, the last line is in bold, e.g. **"Successful: 3 matched, 1 no matches."** or **"Stopped early: …"**.
- **You can use the other pages while it runs.** The run continues in the background, and the run indicator in the header shows its progress.

When the run finishes:

- The status line gives the totals, e.g. "Done: 8 job(s) with suggestions, 2 with none, 0 not judged yet."
- The picked folder and files are cleared from the page, because they are now stored.
- After **Find matches**, a **See results** button appears. It opens the Results page.

If the run stops on a problem, the status line starts with **"Stopped:"** and says why.

#### e. The Gemini quota line and question

Under the progress box, a small line shows **today's Gemini use**, e.g. "Gemini today: 12 of 500 requests, 84,210 tokens."

Before sending anything, the app estimates how much of today's free allowance the run will use. If the run would use most of what's left, it **stops and asks you** in a pop-up, "Use more of today's Gemini quota?":

- **Yes, go ahead** sends the requests. If the run needs more than is left today, Yes sends only the requests that fit today, and the rest wait for the next run.
- **Not now** stops before sending. Jobs not judged stay "Not judged yet". Run **Find matches** again later, for example the next day after the allowance resets.

While the question is waiting, the header shows "Answer needed on Find matches" on every page.

---

### 3.2 Results

**What it's for:** This is where you review Gemini's suggestions. There is **one card per open job**, showing the contractors suggested for it. You decide on each one here.

**What "matches" means:**

- **A fit** is a contractor Gemini judges able to do the job.
- **A partial** is a contractor who meets some of the job but not all of it.
- **For each job the app shows:**
  - **up to 3 clear fits**, the best first;
  - or, when nobody clearly fits, **the single best partial**, for you to check by hand;
  - or **nobody**, when no one in your list fits.

IMAGE 5.1 (in section 5.3) shows a green and a yellow job card on this page.

#### a. The summary line

At the top, a line counts the jobs by outcome, e.g. "5 job(s) with clear fits · 2 to check by hand · 1 with no match · 0 not judged yet".

#### b. The job card

**[IMAGE 3.1: The top band of a green job card: job title, "See on Jobs" and the ↗ button]**

**The coloured band (top of the card):**

| Band colour | Label | Meaning |
|---|---|---|
| Green | **Clear fits** | One to three contractors fit this job. |
| Yellow | **No clear fit: best partial match, check by hand** | Nobody fits fully. The closest contractor is shown for you to judge. |
| No colour (light purple) | **No match: nobody in the contractor list fits** | Gemini found no one suitable. |
| No colour (light purple) | **Not judged yet: click Find matches** | The job hasn't been sent to Gemini yet (for example the quota ran out, or you answered Not now). |

**In the band:**

| Element | What it does |
|---|---|
| **Job title** | The job title. "- FT" or "- PT" after it means full-time or part-time, when known. |
| **See on Jobs** | Opens the Jobs page, scrolled to this job, with its approved candidates table open. The card is outlined in purple for a moment so you can spot it. |
| **↗ (round button)** | Opens the original job posting in your web browser. |

**Under the band, a row of tags** shows what's known about the job: company, location, work mode (On-site / Hybrid / Remote), hours per week, pay (e.g. "$90/hour", "$95,000/year"), and the outcome. The **contact line** shows the posting's contact person and email. The **copy** button next to the email copies it to your clipboard. If there's no email, it says "No contact email in the posting". The app never sends email itself.

#### c. Each suggested contractor

**[IMAGE 3.2: One contractor box, with the verdict tag, score, reason and the three decision buttons]**

| Element | What it shows or does |
|---|---|
| **Name and headline** | The contractor's name and one-line professional headline. |
| **Verdict tag: "fit" or "partial"** | Gemini's verdict, coloured by score: dark green (90 to 100), green (70 to 89), yellow (40 to 69), light yellow (below 40). |
| **"· score N"** | Gemini's fit score out of 100. |
| **"reason only"** (italic) | Gemini judged this contractor but didn't describe them in detail, so only the one-line reason is known. Check them by hand. |
| **"Not available for new projects"** (grey tag) | The contractor has been switched off on the Talent page since this suggestion was made. |
| **The reason** | One sentence from Gemini on why they fit, or partly fit. |
| **Details** (click to open) | The full explanation. See below. |
| **Approve** (green) | Records your approval. The contractor then appears on the Jobs page as an approved candidate for this job. |
| **Reject** (red) | Opens a pop-up asking **why** (required) with optional notes. See below. |
| **Needs info** (yellow) | Records that you need more information before deciding. |

**Inside Details:**

**[IMAGE 3.3: The Details section open, with the Profile and Résumé buttons (Résumé grey: none on file), the "Meets" table and the Missing list]**

- **Profile** opens the contractor's full profile (read-only here; it can be edited on the Talent page).
- **Résumé** opens their résumé PDF inside the app. If no résumé is on file, the button is grey and can't be clicked.
- **Meets** is a table with two columns: **TALENT ASSET** (the contractor's skill or result) and **JOB REQUIREMENT** (the requirement it meets).
- **Missing** lists job requirements the contractor doesn't show.
- **Flags** lists warnings (for example a location or language concern).
- A grey note may say **"Something Gemini listed could not be found in their profile or the job, so it was left out."** This means the app removed an unsupported claim, so only checked information is shown.

**After you decide:**

- A **decision tag** appears at the top right of the contractor's box: "Approved", "Rejected (reason)" or "Needs info".
- The box's **left edge** turns green, red or yellow.
- The **↺ (reset)** button next to the tag clears the decision, in case you clicked by mistake or changed your mind.
- You can change a decision at any time by clicking another button. The latest decision is the one that counts. Every decision is saved with your name and the time.

**[IMAGE 3.4: A contractor box after approval, with the green left edge, the "Approved" tag and the reset button]**

#### d. Rejecting a contractor

**[IMAGE 3.5: The "Why reject this match?" pop-up]**

1. Click **Reject**.
2. Pick a **Reason**: Wrong skills, Seniority, Location, Language, Not a contract, Duplicate, Posting expired, or Other.
3. Optionally add **Notes**.
4. Click **Reject** to confirm, or **Cancel**.

Rejected contractors are **hidden from the card** straight away and moved under **"Show rejected (N)"** at the bottom of the card. Click it to see them. To bring someone back, open **Show rejected** and click **↺** (reset) on their decision. Reasons are saved and are used to fine-tune the matching over time.

**[IMAGE 3.6: The "Show rejected (1)" section opened at the bottom of a job card]**

#### e. The buttons at the bottom of the page

| Button | What it does |
|---|---|
| **Export to Excel** | Saves a spreadsheet of the current suggestions for every open job, then shows the file in Finder or File Explorer. See [6.3](#63-export-to-excel-the-results-spreadsheet). |
| **Add jobs / new search** | Goes back to Find matches. |

---

### 3.3 Jobs

**What it's for:** This page lists **every job** in the app, open and closed, A to Z. On it you can see where each job stands, track the applications of approved candidates, and close, reopen or delete jobs.

**[IMAGE 3.7: The top of the Jobs page: search box, filter button, summary line, and a red and a green job card]**

#### a. The top of the page

| Element | What it does |
|---|---|
| **The summary line** | Counts the jobs, e.g. "24 job(s) · 18 scanned (12 with matches, 6 with no match) · 4 not scanned yet · 2 closed". |
| **Search by job title or company** | Shows only jobs whose title or company contains every word you type. Accents don't matter: "quebec" finds "Québec". The **✕** clears the search. |
| **Filter (funnel icon)** | A drop-down menu: **All (A–Z)**, **With approved candidates**, or **Unavailable**. When a filter other than All is on, the button shows its name in purple. |

Jobs are listed with open jobs first, A to Z, then closed jobs, A to Z. When you change a job, its card keeps its place until you leave and come back to the page.

#### b. Card colours: the job's state

| Colour | State label | Meaning |
|---|---|---|
| **Green** | Scanned | Matched: at least one contractor was suggested. |
| **Red** | Scanned · no match | Checked, nobody suggested. The job stays open, so it will be checked again against new contractors. |
| **Yellow** | Not scanned yet | Waiting for Gemini: a new or reopened job, or new contractors not yet checked against it. |
| **Grey** | Closed | Completed (someone was hired) or marked Unavailable. Closed jobs are never sent to Gemini and don't appear on Results. |

#### c. What each card shows

**[IMAGE 3.8: One open job card, with the "See on Results", ↗ and "Unavailable" buttons, and "Approved candidates" opened (none yet)]**

- **Job title**, with "- FT" or "- PT" when known.
- **Company · Location**, then **work mode · hours per week · pay**.
- **Contact line:** contact person and email, with the copy button.
- **State line:** for example "Scanned · 3 matches · best score 92", "Scanned · best score 58" (one partial), "Scanned · no match", "Not scanned yet", or "Closed · completed" / "Closed · unavailable".

**Buttons on the card:**

| Button | Shown on | What it does |
|---|---|---|
| **See on Results** | Open jobs | Opens this job's card on Results. |
| **↗ (round button)** | All jobs | Opens the original posting in your browser. |
| **Unavailable** | Open jobs | Closes the job because the posting expired or isn't valid. It is no longer matched and leaves Results. |
| **Reopen** | Closed jobs | Makes the job open again. On the next Find matches, only contractors not yet judged for it are sent to Gemini. |
| **🗑 Delete (red, bottom-right)** | Closed jobs only | Deletes the job from the app (see below). |

There is no "Completed" button: **a job is completed automatically when one of its candidates is set to Hired.**

#### d. Approved candidates table

Click **Approved candidates (N)** to open the table of contractors you approved for this job on Results. If there are none, it says "No approved candidates yet. Approve them on Results."

**[IMAGE 3.9: The Approved candidates table, with one candidate, the Application status drop-down and the Save button]**

**[IMAGE 3.9b: The Application status drop-down open, showing the five statuses]**

| Column | Meaning |
|---|---|
| **Candidate** | The contractor's name. |
| **Headline** | Their professional headline. |
| **Score** | Gemini's fit score for this job. |
| **Application status** | A drop-down of where the application stands (see below). |
| **Save** | Saves the status you picked. **The status isn't saved until you click Save.** |

**Application statuses:**

| Status | Use it when |
|---|---|
| **Not referred yet** | Approved, but not yet put forward (the starting status). |
| **Outreached to HR** | You've contacted the hiring company about this candidate. |
| **HR replied, in progress** | The company replied and the process is under way. |
| **Rejection / Ghosted** | The company said no or stopped replying. The row turns grey and is crossed out, with an **Undo** button to bring it back. |
| **Hired** | The candidate got the job. Saving this **marks the job completed** (the card turns grey). |

The same statuses appear, read-only, on the contractor's card on the **Talent** page.

#### e. Deleting a job

Only **closed** jobs can be deleted. To delete an open job, first click **Unavailable**, then click the red **🗑** button in the card's bottom-right corner.

**[IMAGE 3.10: A closed job card, with the Reopen button and the red Delete button]**

A pop-up explains what will happen:

- The job leaves the app: Jobs, Results and future matching. Its suggestions, application statuses and Gemini's answers are deleted.
- If the same job is imported again later, it's sent to Gemini afresh.
- A contractor hired for it still sees it on their Talent card, marked "(removed)".

Click **Delete** to confirm, or **Cancel**.

---

### 3.4 Talent

**What it's for:** This page lists **every contractor** in the app. On it you control **who is available for matching**, view and edit profiles, add or replace résumés, keep a note on each person, and see which jobs they were approved for.

**[IMAGE 3.11: The top of the Talent page: the explanation, the search box and the summary line]**

#### a. The top of the page

- **A short explanation** of how availability and profile edits work.
- **The summary line**, e.g. "32 contractor(s) · 28 available for matching · 4 not available".
- **Search by name or headline:** shows only contractors whose name or headline contains every word you type.

#### b. The contractor card

**[IMAGE 3.12: One contractor card: the Available switch, name, headline, Profile and Résumé buttons, note box, and "Approved for jobs" opened]**

**Card colour:** white when the contractor is available for matching, grey when not.

| Element | What it does |
|---|---|
| **Available (switch, left)** | Turns the contractor on or off for matching. **It saves as soon as you flip it.** Off means they are no longer sent to Gemini, and their open suggestions make room for other contractors. Check with the contractor before switching them off. A hire never changes this switch. |
| **Name** | The contractor's name. |
| **"Not available for matching"** (grey tag) | Shown when the switch is off. |
| **"Profile says: open / not open to contract work"** (tag) | The contractor's own answer in the contractor list, shown when it differs from your switch (yellow), or when they said they're not open and nobody has switched them yet (grey). |
| **Headline** | Their one-line professional headline. |
| **"Set available by <name> on <date>."** | Who last flipped the switch, and when. |
| **Profile** | Opens the profile pop-up, where you can edit it and write a note (see below). |
| **Résumé** | Opens their résumé. If none is on file, the button is grey: click it to **add a PDF**. |
| **The note box** | Shows your note on this contractor, or "No note". You write the note in the Profile pop-up. |
| **Approved for jobs (N)** | Click it to open the table of jobs this contractor was approved for: **Job title, Company, Location, Application status** (read-only; set on the Jobs page). Closed jobs are marked "(closed)", deleted jobs "(removed)", and rejected or ghosted applications are greyed out. |
| **🗑 Delete (red, bottom-right)** | Only shown when the contractor is switched **off**. Deletes the contractor (see below). |

#### c. The profile pop-up (view, edit, note)

**[IMAGE 3.13: The profile pop-up in view mode, with the Note box and the Column / Value table]**

The pop-up shows everything the contractor list holds about the person, as a two-column table (**Column** and **Value**), plus a **Note** box at the top.

- **Note:** type anything useful to you (for example "Prefers remote; available from January"). It's yours: it isn't sent to Gemini, and **it survives contractor imports**.
- **Edit** turns the values into boxes you can change. Lists (skills, achievements, titles and so on) take **one item per line**. The talent ID can't be edited.
- **Save** checks every field and stores your changes and note. If you changed something Gemini uses, the message says "Saved. They will be matched again on the next Find matches run."
- **✕** closes the pop-up without saving.

**[IMAGE 3.14: The profile pop-up in edit mode]**

**Important:** the contractor folder you import is the master copy. **Your edits stay until the master copy changes that contractor.** Then only the fields that changed in the master copy are taken, and your other edits stay. If you and the master copy changed the same field, the master copy's value is used. Your note is always kept. To be sure an edit lasts, also correct it in your source contractor file.

On the Results page the same pop-up opens **read-only** (no Edit, Save or Note).

#### d. Résumés

**[IMAGE 3.15: The résumé viewer, with the "Replace résumé" button]**

- **No résumé on file:** the Résumé button is grey. Click it, pick a PDF, and it's added ("Résumé added.").
- **Viewing:** click Résumé to read the PDF inside the app.
- **Replacing:** in the viewer, click **Replace résumé** and pick a new PDF. A yellow bar says "New résumé picked. Save replaces the one on file (the old copy is kept)." Click **Save** to replace it, or **Cancel** to keep the current one.
- Résumés are for your eyes only. **They are never sent to Gemini.**

#### e. Deleting a contractor

First switch the contractor **off**, then click the red **🗑** button. The pop-up explains:

- Everything about them leaves the app: profile, résumé, availability, suggestions, your decisions on them and their application statuses.
- Your contractor folder is not touched: **importing it again adds them back.**

Click **Delete** to confirm, or **Cancel**.

---

### 3.5 Settings

**What it's for:** This page holds your Gemini key, your reviewer name, where the data is kept, and backup (export and import).

**[IMAGE 3.16: The Settings page, full view]**

| Card | Elements | What they do |
|---|---|---|
| **Gemini key** | "A key is saved." / "No key saved yet." | Whether a key is stored. The key itself is never shown. |
| | **Paste a new key** (with an eye icon) | Paste a key here. The eye shows or hides what you pasted. |
| | **Save key** | Stores the key on this computer, replacing any earlier key. |
| **Your name** | **Reviewer** box, **Save name** | The name saved with each of your decisions and availability changes. If several people use the app, each should set their own name. |
| **Data folder** | The folder path, **Show in folder** | Where all jobs, contractors, résumés, decisions and exports are stored. **Show in folder** opens it in Finder or File Explorer. |
| **Back up or move the app** | **Export all data**, **Import a backup** | Save all the app's data in one password-protected file, or replace the app's data with such a file. See [section 6](#6-export--import). |

**Where the data folder is:**

- **Mac:** your user folder › Library › Application Support › dogoodtalent
- **Windows:** `%APPDATA%\dogoodtalent` (type it into File Explorer's address bar)

The data folder holds personal information. **Keep your computer password-protected.** Don't edit or move files in it while the app is running.

---

## 4. Input format

The app takes two kinds of input: **jobs** and **contractors**.

### 4.1 Jobs

**Accepted job files: `.csv` and `.txt` only.** You can also enter jobs one at a time with **Add a job by hand** on Find matches (see 3.1 c).

| File type | Use it for |
|---|---|
| **Jobs CSV** (`.csv`) | Several jobs at once, one row per job, typed or pasted into a spreadsheet. **Recommended.** |
| **Text file of links** (`.txt`) | A list of job posting links, one per line. The app opens each link and reads the posting. |
| **Text file of one posting** (`.txt`) | One posting pasted as text, with a short header. |

#### 4.1.1 Jobs CSV

The easiest way to start is **Find matches › Jobs › Get CSV template**. It saves a correctly formatted file with two example rows. Replace the examples with your jobs.

**[IMAGE 4.1: The header row of the jobs CSV template, open in Excel]**

**File rules:**

- **Row 1 is the header**, with the column names below, in any order. Columns you don't need can be left out, except the two required ones. A column with an unknown name makes the whole file refused, and the message names it.
- **One row per job.**
- **Save as "CSV UTF-8 (comma delimited)"** in Excel (File › Save As › file format). Other CSV types can garble accents (é, à) and are refused.
- **A row with a problem is skipped and reported** ("Not imported: Row 5: …"). The other rows still go in. Fix the row and pick the file again: rows already imported are skipped.

**Columns:**

| Column name | Required | What to enter | Example |
|---|---|---|---|
| `url` | **Yes** | The posting's web address, starting with `http://` or `https://`. It's how the app recognizes the same job again. | `https://www.example.ca/jobs/12345` |
| `job_title` | **Yes** | The title, as written in the posting. | `Data Analyst (6-month contract)` |
| `company` | No | The hiring company, or the agency if that's all the posting names. | `Example Insurance Inc.` |
| `contact_person` | No | The HR or hiring contact's name. | `Jordan Lee` |
| `contact_email` | No | The contact's email address. Must be a valid email. If empty, an email written in the responsibilities or qualifications is used. | `jordan.lee@example.ca` |
| `location` | No | City and province. | `Toronto, ON` |
| `work_mode` | No | `on-site`, `hybrid` or `remote`. French words also work (`sur place`, `hybride`, `à distance`, `télétravail`). | `hybrid` |
| `hours_per_week` | No | A number from 1 to 80. 30 or more shows as full-time (FT), fewer as part-time (PT). | `37.5` |
| `pay` | No | A number in Canadian dollars, or a range (the **lower end** is kept). `$`, spaces and thousands separators are fine. | `90`, `85–95`, `$95,000` |
| `pay_type` | Only when `pay` is filled | `hourly` or `salary` (per year). French also works (`horaire`, `salaire`, `annuel`). | `hourly` |
| `posted_date` | No | The date in **YYYY-MM-DD** form, or with the month written out. A date written only in numbers, like 03/04/2026, is **refused** because the day and month can't be told apart. | `2026-11-08`, `8 Nov 2026`, `8 novembre 2026` |
| `responsibility` | No | What the person will do. Several items, **one per line inside the cell** (Alt+Enter in Excel for Windows; Control+Option+Return in Excel for Mac), or separated by `|`. | `Build Power BI dashboards|Write SQL reports` |
| `qualification` | No | Required skills, experience, languages. Same layout as `responsibility`. | `3+ years of SQL|French is an asset` |

Formatting copied from web pages (bullets, numbering, bold, odd spaces, empty lines) is cleaned out of every cell automatically.

**The more you fill in, the better the matching.** In particular, `responsibility` and `qualification` are what Gemini compares with each contractor's profile. A job with only a title gives Gemini little to go on.

#### 4.1.2 Text file of links (`.txt`)

A plain text file with **one posting link per line**. Lines starting with `#` are notes to yourself and are ignored. Empty lines are ignored.

```
# Postings found on 18 November
https://www.example.ca/careers/job/12345
https://jobs.example.org/posting/data-analyst-contract
```

- The app opens each link and reads the posting: title, company, location, pay, work mode, contract type, responsibilities and requirements, in English or French.
- **Automatic checks:** postings read this way are checked for being **in Canada** and **a contract**. Postings that are clearly not (for example a permanent role, or a job outside Canada) are set aside and not matched.
- **Some sites can't be read automatically**, such as pages that need you to log in, or pages that only appear once the browser has run them (for example Workday, Zoho Recruit or BambooHR career sites). For those, use a jobs CSV row, the **Add a job by hand** form, or a text file of the pasted posting (below).
- A file counts as a links file only when **every** non-note line starts with `http://` or `https://`. Otherwise it is read as a pasted posting.

#### 4.1.3 Text file of one pasted posting (`.txt`)

One posting per file: a short header, a line with three dashes `---`, then the posting text pasted underneath.

```
url: https://www.example.ca/careers/job/12345
title: Senior Business Analyst (12-month contract)
company: Example Insurance Inc.
location: Toronto, ON (Hybrid)
employment_type: Contract
posted: 2026-10-18
---
<paste the full posting text here>
```

| Header line | Required | Meaning |
|---|---|---|
| `url:` | **Yes** | The posting's web address. |
| `title:` | **Yes** | The job title. |
| `company:` | No | The hiring company. |
| `location:` | No | City and province. |
| `employment_type:` | No | E.g. Contract, Temporary, Full-time. |
| `posted:` | No | The posting date, as YYYY-MM-DD. |

- Lines in the header starting with `#` are ignored.
- **Nothing after `---`?** The job is saved as a placeholder that "needs details". Paste the text into the same file later and add it again.
- The pasted text goes through the same automatic checks as links (Canada, contract).

#### 4.1.4 Duplicates and changes

- **A job is recognized by its link.** The same link added again, in any format, is skipped. The app also spots the same job posted on several sites, and stores it once.
- **To change a job that's already in the app:** on the Jobs page, click **Unavailable**, then **Delete**, then import the corrected version.

### 4.2 Contractors

Contractors are loaded as a **folder** with **Find matches › Contractors › Choose folder…**.

#### 4.2.1 Folder layout

```
My contractors/                (any folder name)
  contractors.csv              exactly ONE contractor file at the top of the folder
  resume/                      optional; may also be called "resumes"
    TAL-CAN-001.pdf            one PDF per contractor, named with their talent ID
    TAL-CAN-002.pdf
```

**[IMAGE 4.2: A contractor folder in File Explorer: contractors.csv and the resumes folder]**

**[IMAGE 4.2b: Inside the resumes folder: one PDF per contractor, each named with the contractor's talent ID]**

- **The contractor file:** exactly **one** `.csv` (recommended) or `.xlsx` file at the top of the folder. None, or two or more, is an error.
- **The `.xlsx` option** is for the master talent workbook in its agreed layout. For anything else, use the CSV format below.
- **Résumés (optional):** a folder called `resume` or `resumes` (any capitalization) holding **PDF files only**, each named **exactly with the contractor's talent ID** (e.g. `TAL-CAN-001.pdf`). A PDF named any other way is skipped and listed on screen. Each file must be a real PDF.
- Hidden files and temporary Office files (starting with `~$`) are ignored.

#### 4.2.2 Contractor CSV: file rules

| Rule | Detail |
|---|---|
| Format | **CSV UTF-8 (comma delimited)**. |
| Header | Row 1, with the column names below, **in any order**. |
| Required columns | `talent_id`, `talent_name`, `rate_expectation`. |
| Optional columns | Can be left out entirely, or present with empty cells. |
| Unknown or repeated column names | The file is refused. **There are no phone, email or address columns, and adding one makes the file refused.** |
| Lists | Several items in one cell, separated by `|`, e.g. `Power BI|SQL|Excel`. |
| Yes / no | `true` or `false`. |
| Numbers | Plain, with a dot for decimals (`37.5`). No units or `$`. |
| All or nothing | **One bad row refuses the whole file**, and the message names the row and column. Nothing is changed until the file is correct. |

#### 4.2.3 Contractor CSV: columns

"Sent to Gemini" means the value appears on the anonymous card Gemini reads.

| Column name | Required | What to enter | Sent to Gemini |
|---|---|---|---|
| `talent_id` | **Yes** | A **stable, unique ID** for each person, which never changes between files. Letters, digits and dashes, e.g. `TAL-CAN-001`. Résumé PDFs are named with it. | No (an anonymous code is used) |
| `talent_name` | **Yes** | Full name. Shown to you only. | **No** |
| `rate_expectation` | **Yes** | Hourly rate in CAD, e.g. `90` or `52.5`, or the words `Industry Standard` when unknown. | Yes |
| `location` | No | **City and province only**, e.g. `Toronto, ON`. No street address or postal code. | Yes |
| `standardized_headline` | No | One-line professional headline, e.g. `Bilingual Data Analyst (Power BI, SQL)`. | Yes |
| `executive_summary` | No | Professional summary. Only the first 300 words are sent. | Yes |
| `core_strengths` | No | Skills and tools (list). | Yes |
| `proof_points` | No | Concrete achievements (list), e.g. `Cut month-end reporting from 5 days to 2`. | Yes |
| `main_industry` | No | Industries (list), e.g. `Public sector|Retail`. | Yes |
| `search_keywords` | No | Extra matching words (list). | Yes |
| `target_titles` | No | Job titles the person wants (list). | Yes |
| `seniority` | No | e.g. `Junior`, `Intermediate`, `Senior`, `Lead`. | Yes |
| `years_experience` | No | Years in the profession (number). | Yes |
| `weekly_hours` | No | Hours per week available (number). | Yes |
| `primary_profession` | No | The person's main profession, written **exactly** as one of the names in [Appendix B](#appendix-b-profession-names), in lowercase, e.g. `data analysis and business intelligence`. | Yes |
| `secondary_professions` | No | Up to 2 more names from Appendix B (list). | Yes |
| `languages` | No | `en`, `fr`, or `en|fr`. | Yes |
| `contract` | No | `true` if open to contract work (the default when empty), `false` if not. A contractor marked `false` isn't matched unless you switch them on in Talent. | No |

**Tips for good matches:**

- **Put the most important items first in each list.** Each list is cut to its first 15 items.
- **Profiles with a summary and strengths match much better** than thin ones.
- **Don't put names, emails, phone numbers or links in any text field.** A contractor whose text still contains contact details after automatic cleaning is **left out of matching**, as a privacy safeguard.
- **Never invent information.** Reviewers rely on these fields to judge the suggestions.

**Example (made-up people):**

```csv
talent_id,talent_name,location,standardized_headline,executive_summary,core_strengths,proof_points,main_industry,search_keywords,seniority,weekly_hours,rate_expectation,target_titles,contract,primary_profession,secondary_professions,years_experience,languages
TAL-CAN-001,Jordan Lee,"Toronto, ON",Bilingual Data Analyst (Power BI and SQL),"Analyst with 6 years building reporting for public-sector finance teams.",Power BI|SQL|Excel|DAX,Cut month-end reporting from 5 days to 2|Built a KPI dashboard used by 40 managers,Public sector|Finance,dashboards|reporting,Intermediate,30,85,Data Analyst|BI Analyst,true,data analysis and business intelligence,business analysis,6,en|fr
TAL-CAN-002,Sam Roy,"Québec, QC",Rédactrice et stratège de contenu,"Rédactrice bilingue, 10 ans en communication municipale et culturelle.",Rédaction|Révision|Stratégie de contenu|WordPress,Refonte du site d'une ville de 500 000 habitants,Secteur public|Culture,rédaction web|contenu,Senior,20,Industry Standard,Rédactrice|Content Strategist,true,content writing and editing,communications and public relations,10,fr|en
```

#### 4.2.4 What happens when you load the folder again

Loading a contractor folder **updates** the app, matched on `talent_id`:

| In the file | What happens |
|---|---|
| A new `talent_id` | The contractor is added. |
| A known `talent_id` whose row changed since the last import | The fields that changed are taken; edits you made in the app to other fields stay. If something Gemini reads changed, the contractor is checked again against open jobs on the next Find matches. A name change alone doesn't trigger this. |
| A known `talent_id` whose row did not change | Nothing changes, so any edits you made in the app stay. |
| A contractor missing from the file | **Kept**, not removed. To remove someone, delete them on the Talent page. |
| The same `talent_id` twice | The whole file is refused. |
| An empty `talent_id` | The app assigns one (`TAL-CAN-` and the next number). **Avoid this:** always supply stable IDs, so résumés can be named and people are recognized reliably. |

- **Edits made in the app stay** until the file changes that contractor; then only the changed fields are taken from the file. Your **notes are always kept**.
- The app remembers the file as it was last imported (`contractors_master.csv` in the data folder) to tell your edits from changes in the file. The very first import after this feature arrived has nothing to compare with, so it works the old way once: the file's values replace earlier edits.
- **When a profile is new or changed in an import, the Available switch follows the file's `contract` column** (the contractor's own answer).

### 4.3 Where to get jobs

_(To be added.)_

### 4.4 Where to get contractors

_(To be added.)_

---

## 5. General flow of the app

These are the common ways to use the app, step by step.

### 5.1 First-time setup

1. **Install** the app and **allow it to open** (sections 2.2 and 2.3).
2. Go to **Settings**. Paste your **Gemini key** and click **Save key**. Type **your name** and click **Save name** (section 2.5, IMAGE 2.10).
3. Go to **Find matches** (IMAGE 1.1). Under **Contractors**, click **Choose folder…** and pick your contractor folder. Check the summary line: the number of contractors and résumés, and any skipped PDFs.
4. Under **Jobs**, click **Choose files…** and pick your jobs CSV or text file. Check the "Added …" line and any "Not imported" rows.
5. **Recommended the first time:** click **Ingest** to store everything without using Gemini. Then look at the **Talent** and **Jobs** pages to check that everyone and everything loaded correctly.
6. Back on **Find matches**, click **Find matches**. If the quota question appears, answer it (3.1 e). Wait for the bold result line. You can watch the progress from any page in the header (IMAGE 3.0b).
7. Click **See results** and continue with 5.3.

### 5.2 Adding new jobs (day to day)

1. Gather new postings into a jobs CSV (from the template), a text file of links, or a pasted-posting text file. For one or two jobs, **Add a job by hand** is quickest.
2. On **Find matches**, add them under **Jobs** (**Choose files…** or **Add a job by hand**). Leave **Contractors** empty if your list hasn't changed.
3. Click **Find matches**. Only the new jobs are sent to Gemini. Jobs already judged aren't asked again.
4. Click **See results**.

### 5.3 Reviewing suggestions

1. On **Results**, start with the **green** cards (clear fits), then the **yellow** cards (check by hand).

   **[IMAGE 5.1: Results with a green "Clear fits" card and a yellow "No clear fit" card]**

2. For each contractor, read the **reason**. Open **Details** to see what they meet and miss, any warnings, and their **Profile** and **Résumé** (see IMAGE 3.3).
3. Decide: **Approve**, **Reject** (pick a reason), or **Needs info**.

   **[IMAGE 5.2: A card with one contractor approved, one still to decide, and one rejected under "Show rejected (1)"]**

4. Clicked the wrong button? Click **↺** next to the decision to reset it. Rejected contractors are under **Show rejected**.
5. Use **↗** to open the original posting, and the **copy** button to copy the contact email for your outreach (sent from your own email program).

### 5.4 Following up an approved candidate

1. On **Results**, click **See on Jobs** on the job's card (or go to **Jobs** and search for it).

   **[IMAGE 5.3: The Jobs page scrolled to the job, outlined in purple, with Approved candidates open]**

2. In **Approved candidates**, pick the new **Application status** for the candidate and click **Save**:
   - after contacting the company: **Outreached to HR**;
   - when they reply: **HR replied, in progress**;
   - if they decline or stop replying: **Rejection / Ghosted** (use **Undo** if that changes);
   - when the candidate gets the job: **Hired**.

   **[IMAGE 5.4: The application status with "Hired" selected, before clicking Save]**

3. Saving **Hired** marks the job **completed**: its card turns grey and it leaves Results. The contractor's **Talent** card shows the job and status under **Approved for jobs**.

   **[IMAGE 5.5: The job card turned grey, "Closed · completed", after saving "Hired"]**

### 5.5 Adding or updating contractors

1. Update your contractor file (add rows, correct details), and put any new résumés, named with their talent IDs, into the `resume` folder.
2. On **Find matches**, under **Contractors**, click **Choose folder…** and pick the folder.
3. Click **Ingest** to store the changes and check them on **Talent**, or click **Find matches** to store them and match straight away. New or changed contractors are checked against all open jobs.

### 5.6 When a contractor isn't looking for work

1. Go to **Talent** and find the contractor (use the search).
2. Flip the **Available** switch off. It saves immediately, with your name and the date.

   **[IMAGE 5.6: A contractor card switched off: grey, with "Not available for matching", who switched it and when, and the red Delete button]**

3. They're no longer sent to Gemini, and their open suggestions make room for others on the next run. Switch them back on when they're available again.

### 5.7 When a posting expires or a job is filled elsewhere

1. Go to **Jobs** and find the job.
2. Click **Unavailable**. The job turns grey, leaves Results, and is no longer matched.
3. If it comes back, click **Reopen**. Optionally, click the red **🗑** on a closed job to delete it from the app.

   **[IMAGE 5.7: Two closed (grey) job cards, one completed and one unavailable, each with the Reopen and Delete buttons]**

### 5.8 Sharing the suggestions with your team

1. On **Results**, click **Export to Excel** at the bottom.
2. The spreadsheet is saved and shown in Finder or File Explorer. Open it in Excel.
3. It contains contractor names: share it only within your team.

### 5.9 Handing over to a colleague or moving to a new computer

1. On the current computer: **Settings › Export all data**, choose a password, and save the file (section 6.1).
2. Give the file to the colleague, and give them the password **separately** (for example by phone).
3. On the new computer: install the app (section 2), then **Settings › Import a backup** (section 6.2).
4. On the new computer, enter a **Gemini key** and **your name** in Settings. They aren't in the backup.

---

## 6. Export / Import

The app has two kinds of export:

| Export | Where | What it's for |
|---|---|---|
| **Export all data** (with **Import a backup**) | Settings › Back up or move the app | A complete, password-protected backup of the app's data, to keep safe, move to another computer, or hand over to another person. |
| **Export to Excel** | Results, bottom of the page | A spreadsheet of the current suggestions, to read or share with your team. It can't be imported back. |

**[IMAGE 6.1: The "Back up or move the app" card in Settings, with the Export all data and Import a backup buttons]**

### 6.1 Export all data (backup)

**What it saves:** all jobs, contractors, résumés, your decisions and notes, application statuses, availability switches, and Gemini's saved answers. Everything goes into **one password-protected `.zip` file**.

**What it leaves out:**

- **The Gemini key** and **your reviewer name.** These never leave the computer. Enter them again after an import.
- The app's own automatic safety copies.

**How to export:**

1. Go to **Settings** and click **Export all data**.
2. Type a **password** of **at least 10 characters**, and type it again. The eye icon shows what you typed.

   **[IMAGE 6.2: The "Export all data" pop-up, with the two password boxes]**

3. Click **Export**. A save dialog asks where to save the file; its name includes the date and time.
4. A message confirms what was saved, e.g. "Exported 24 job(s) and 32 contractor(s) (4.2 MB)."

**About the password:**

- **Without the password, the backup can't be opened, and the password can't be recovered.** Keep it somewhere safe, apart from the file.
- The file is encrypted, but it still holds personal information. Store it carefully.

### 6.2 Import a backup

**Importing replaces all of this app's data** with the backup's contents. It doesn't merge them. Your current data is **not deleted**: it is moved aside so that the import can be undone.

1. Go to **Settings** and click **Import a backup**.
2. Click **Choose backup…** and pick the `.zip` file made with Export all data.
3. Type its **password** and click **Check backup**.

   **[IMAGE 6.3: The "Import a backup" pop-up, with "Choose backup…", the password box and "Check backup"]**

4. The app **checks the backup completely before changing anything**: the password, that no file is damaged or altered, and that every file is valid. If anything is wrong, a message says what, and nothing changes.
5. If the check passes, a confirmation shows **what you have now** (jobs and contractors) next to **what the backup holds** (its date, app version, jobs, contractors, files and size).

   **[IMAGE 6.4: The "Replace this app's data?" confirmation, comparing current data with the backup]**

6. Click **Replace data** (red) to import, or **Cancel** to stop without changes.
7. A message confirms the import and names the folder where your previous data was kept. The app returns to Settings.
8. **Enter the Gemini key and your name** in Settings if this is a new computer.

**Undoing an import:** the previous data is kept in the data folder under `backups`, in a folder named `before-import-` followed by the date and time. To go back, ask the person who supports the app to put that folder back in place.

### 6.3 Export to Excel (the results spreadsheet)

On **Results**, **Export to Excel** saves a spreadsheet (a `.csv` file that opens in Excel) named `llm-matches-` followed by the date and time. The app then shows it in Finder or File Explorer.

**What it contains:**

- **One row per suggested contractor**, for every open job, in the order shown on Results.
- **A job with no match, or not judged yet, gets one row** saying so.
- **Rejected contractors and closed jobs are left out.**

| Column | Meaning |
|---|---|
| `job_title`, `company`, `location` | The job. |
| `job_url` | The link to the posting. |
| `job_id` | The app's internal reference for the job. |
| `result` | `match`, `no match`, or `not judged yet`. |
| `rank` | The contractor's position on the job's card (1 = first). |
| `verdict` | `fit` or `partial`. |
| `detail` | `full`, or `reason only` (Gemini didn't describe the contractor in detail). |
| `fit_score` | Gemini's score out of 100. |
| `talent_id`, `talent_name`, `headline` | The contractor. |
| `reason` | Gemini's one-line reason. |
| `requirements_met` | What they meet (items separated by `|`). |
| `requirements_missing` | What's missing (items separated by `|`). |
| `red_flags` | Warnings (items separated by `|`). |
| `evidence_check` | `verified`, or a note that something couldn't be found and was left out. |
| `model` | Which Gemini model made the suggestion. |
| `match_id` | The app's internal reference for the suggestion. |

The spreadsheet **contains names**: keep it within your team. It is a snapshot. Decisions are made in the app, not in the spreadsheet, and changes made in the spreadsheet don't go back into the app.

### 6.4 Automatic safety copies

Whenever the app rewrites one of its files, it first keeps a dated safety copy in the data folder. **Safety copies older than 30 days are cleared automatically** when the app starts. Your exports, résumé copies and the `before-import-` folders are never cleared automatically. These safety copies are not a replacement for **Export all data**: make a backup regularly, and before any big change.

---

## Appendix A: Troubleshooting

| Problem | What to do |
|---|---|
| **The window stays blank.** | Close the app and open it again. |
| **"Add your Gemini key in Settings"** | Save a key in Settings (section 2.4 and 2.5). |
| **A job shows "Not judged yet".** | The day's Gemini allowance ran out, you answered "Not now", or the run was stopped. Click **Find matches** again later. Jobs already judged aren't asked again. |
| **"Expected exactly one contractor file…"** | The contractor folder must have exactly one `.csv` or `.xlsx` at its top level. Move any extra file out. |
| **"Skipped (not named by a talent ID)"** | Rename the PDF to the contractor's exact talent ID, e.g. `TAL-CAN-001.pdf`, and pick the folder again. |
| **The contractor file is refused.** | The message names the row and column. Common causes: an unknown or repeated column name, a phone or email column, a repeated `talent_id`, text in a number column. Fix it and pick the folder again. |
| **"not UTF-8 text"** | In Excel, save the file as **CSV UTF-8 (comma delimited)**. |
| **A jobs CSV row is "Not imported"** | The message says why: often an empty link or title, a date written only in numbers, or pay without `pay_type`. Fix the row and pick the file again. |
| **A link from a text file produced no job.** | The site may need a login or only build its page in the browser. Add the job as a CSV row, with the form, or as a pasted-posting text file. |
| **A job I changed in my file didn't update.** | Jobs already in the app are skipped. Mark it Unavailable, delete it on Jobs, then import it again. |
| **My edit to a profile disappeared.** | The contractor file changed that same field, so the file's value was used (or it was the first import after the master-copy rule arrived). Correct the source contractor file too. |
| **A contractor is never suggested.** | Check on Talent that they're **Available**. Thin profiles (no summary or strengths) match less well. A profile with contact details left in its text is left out of matching. |
| **"A run is already going"** | Only one run at a time. Watch its progress on Find matches or in the header. |
| **Anything else** | Note what you clicked and what the message said, and send it to the person who supports the app, with the file `check.txt` from the data folder if there is one. |

---

## Appendix B: Profession names

Use these names, **exactly as written and in lowercase**, in the contractor columns `primary_profession` and `secondary_professions`.

**Business, marketing, creative and technology**

- digital project management
- construction project management
- program coordination
- operations management
- human resources
- recruiting and talent acquisition
- payroll and compensation
- finance and accounting
- sales and business development
- client services and account management
- marketing management
- digital and performance marketing
- brand strategy and management
- content writing and editing
- social media and community management
- communications and public relations
- events
- graphic and visual design
- creative direction
- ux and product design
- animation and motion
- media and content production
- product management
- business analysis
- software development
- data engineering
- data analysis and business intelligence
- machine learning and ai
- regulatory and compliance
- information and records management
- training and facilitation

**Business, finance and administration**

- administrative and office support
- customer service and call centre
- purchasing and procurement

**Natural and applied sciences**

- it support and infrastructure
- cybersecurity
- civil and structural engineering
- mechanical and electrical engineering
- engineering technology and drafting
- laboratory and life sciences
- architecture and urban planning

**Health**

- nursing
- personal support and health care aides
- physicians and medicine
- allied health and therapy
- pharmacy
- medical laboratory and diagnostic imaging

**Education, law, social, community and government services**

- school teaching
- post-secondary teaching
- early childhood education
- social work and counselling
- community and support work
- law and paralegal
- policy and government programs
- public safety and emergency response

**Sales and service**

- retail sales
- hospitality and food service
- security services
- cleaning and facilities maintenance

**Trades, transport and equipment operators**

- electrical trades
- plumbing and hvac
- construction trades
- mechanical repair and maintenance
- welding and metal fabrication
- equipment operation and driving

**Natural resources, agriculture, manufacturing and utilities**

- agriculture and natural resources work
- manufacturing and production
- warehouse and logistics operations

---

## Appendix C: Glossary

| Term | Meaning |
|---|---|
| **Gemini** | Google's AI, which reads the jobs and the anonymous contractor profiles and suggests matches. |
| **API key / Gemini key** | The code from Google AI Studio that lets the app use Gemini on your account. |
| **Free tier / daily allowance** | The amount of Gemini use Google gives free each day. It resets at midnight Pacific time. |
| **Ingest** | Store contractors and jobs in the app without matching. |
| **Find matches** | Store, then ask Gemini about new jobs and contractors. |
| **Fit / partial** | Gemini's verdict: the contractor can do the job, or meets only part of it. |
| **Score** | Gemini's 0 to 100 rating of how well the contractor fits the job. |
| **Clear fits / best partial / no match / not judged yet** | The outcome of a job on Results. |
| **Scanned / not scanned yet / closed** | A job's state on the Jobs page. |
| **Talent ID** | The contractor's stable reference, e.g. `TAL-CAN-001`. Résumé files are named with it. |
| **Available for matching** | The Talent switch that decides whether a contractor is sent to Gemini. |
| **Application status** | Where an approved candidate's application stands, from "Not referred yet" to "Hired". |
| **Data folder** | The folder on your computer where the app keeps all its data (Settings shows where). |
| **Backup** | The password-protected `.zip` made with Export all data. |
