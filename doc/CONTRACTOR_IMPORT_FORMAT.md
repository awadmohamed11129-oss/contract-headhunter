# Contractor import format (what the app expects)

For anyone building a module that prepares contractor data for do good talent. The module's output is imported the same way a reviewer does it today: **Home › Choose folder**, then **Save without matching** or **Find matches**. Code: `src/jobmatch/sources/resumes.py` (folder), `src/jobmatch/sources/contractor_upsert.py` (file), `src/jobmatch/schemas.py` (`ContractorProfile`).

## 1. Folder layout

```
<any-folder-name>/
  contractors.csv          exactly ONE contractor file at the top (.csv recommended; .xlsx also accepted)
  resume/                  optional ("resume" or "resumes", any capitalisation)
    TAL-CAN-001.pdf        one PDF per contractor, file name = talent_id exactly
    TAL-CAN-002.pdf
```

- **Contractor file:** zero or two or more `.csv`/`.xlsx` files at the top level is an error.
- **Ignored files:** hidden files, `._*` and `~$*` lock files.
- **Résumés:**
  - They must be real PDFs; the app checks the `%PDF-` header.
  - A PDF whose name isn't a known `talent_id` is skipped and listed on screen.
  - They're copied into the app, shown to reviewers only, never read and never sent to Gemini.
- The `.xlsx` route uses the client's master-workbook layout (`config/contractor_import.yaml`). For a new module, produce the **CSV** below, which maps 1:1 to the app's own contractor list.

## 2. CSV file rules

| Rule | Value |
|---|---|
| Encoding | UTF-8 (a BOM is fine) |
| Delimiter / quoting | comma; standard CSV quoting (`"…"` around cells with commas, quotes or line breaks) |
| Header | row 1, exact column names below, in any order |
| Unknown or duplicate columns | the file is rejected |
| Required columns | `talent_id`, `talent_name`, `rate_expectation` |
| Optional columns | may be left out entirely, or present with empty cells |
| Empty cell | the field's default (null / empty list / `true` for `contract`) |
| List cells | items joined with `\|`, e.g. `Power BI\|SQL\|Excel`. A literal `\|` or `\` inside an item is escaped with a backslash (`\|`, `\\`). Empty items aren't allowed. |
| Booleans | `true` / `false` |
| Numbers | plain, with a dot for decimals (`37.5`), no units or currency signs |
| Validation | **all or nothing:** one bad row rejects the whole file, with file, row and column named |

## 3. Columns

"To Gemini" means the value appears on the anonymous card Gemini sees. Names are also scrubbed out of all text before sending.

| Column | Req. | Type | Rules / meaning | To Gemini |
|---|---|---|---|---|
| `talent_id` | ✔ | text | **The key.** Stable for each person across exports. Use filename-safe text (letters, digits, `-`), e.g. `TAL-CAN-001`. Must be unique in the file. | no (an alias like C01 is sent) |
| `talent_name` | ✔ | text | Full name. Personal data: shown to reviewers only, never logged. | **no** |
| `rate_expectation` | ✔ | text | An hourly number in CAD (`90`, `52.5`), or the text `Industry Standard` when unknown. | yes |
| `location` |  | text | **City and province only**, e.g. `Toronto, ON`. No street address or postal code. | yes |
| `standardized_headline` |  | text | One-line professional headline, e.g. `Bilingual Data Analyst (Power BI, SQL)`. | yes |
| `executive_summary` |  | text | Professional summary. Only the first **300 words** are sent (`summary_max_words` in `config/settings.yaml`). | yes |
| `core_strengths` |  | list | Skills and tools. Sent as "Skills". | yes |
| `proof_points` |  | list | Concrete achievements, e.g. `Cut month-end reporting from 5 days to 2`. | yes |
| `main_industry` |  | list | Industries, e.g. `Public sector\|Retail`. | yes |
| `search_keywords` |  | list | Extra matching words. | yes |
| `target_titles` |  | list | Job titles the person wants. | yes |
| `seniority` |  | text | e.g. `Junior`, `Intermediate`, `Senior`, `Lead`. | yes |
| `years_experience` |  | number ≥ 0 | Years in the profession. | yes |
| `weekly_hours` |  | number ≥ 0 | Hours per week available. | yes |
| `primary_profession` |  | text | **Must be a name from `config/professions.yaml`**, lowercase, e.g. `data analysis and business intelligence`. | yes |
| `secondary_professions` |  | list | Up to 2 names from the same file. | yes |
| `languages` |  | list | ISO codes: `en`, `fr`, or `en\|fr`. | yes |
| `contract` |  | `true`/`false` | Open to contract work. `false` means the person isn't sent for matching, unless a reviewer switches them on in Talent. Default `true`. | no |

- **List limits:** each list is cut to **15 items** on the card (`max_list_items` in `config/settings.yaml`, a guess). Put the most important items first.
- **Unknown values aren't rejected:** professions and languages aren't checked at import, so a misspelt profession is simply sent as written. The module should validate them against `config/professions.yaml`.

## 4. How an import is applied

The import is an upsert keyed on `talent_id`:
- **New `talent_id`:** the contractor is added.
- **Known `talent_id` whose row changed since the last import:** the changed fields are taken (see the next point for edits made in the app).
  - If something Gemini sees changed, the contractor is matched again against open jobs.
  - Changes to `talent_name` alone don't trigger matching again.
- **Edits made in the app are kept until the file changes that person.** A reviewer can edit a profile on the Talent screen (Profile › Edit › Save). Each import is compared with the **master record** (`data/contractors/contractors_master.csv`: the rows as the last import brought them, never edited in the app):
  - The person's row is the same as last time: the edited row is kept as it is.
  - The person's row changed: only the **fields that changed** in the file are taken; the other fields keep the reviewer's edits. A field changed both in the file and in the app takes the file's value.
  - No master record yet (the first import after this rule shipped, or a list built before it): the file's row replaces the stored row, as before. The master record is written then.
  - Reviewer notes are kept apart and survive imports.
- **Contractor missing from the file:** kept, not removed. Removing someone is a manual Delete on the Talent screen.
- **Same `talent_id` twice in the file:** the file is rejected.
- **Empty `talent_id`:**
  - The app assigns `TAL-CAN-NNN` (the highest known number + 1).
  - On later imports it reuses that ID if the name matches exactly.
  - **The module should always supply stable IDs instead.** Name matching breaks on spelling changes, and résumés can't be named before an ID exists.

## 5. Privacy rules for the module's output

- **No contact data in any column:**
  - The schema has no phone, email or address columns, and adding one rejects the file.
  - No emails, phone numbers or links inside the text fields either. If any are left after scrubbing, the app **leaves that contractor out of matching**, and the run log shows "contact data left after scrubbing".
- **No names in the text:** don't write the person's name inside `executive_summary` or `proof_points`. It's scrubbed anyway, but the text reads worse to Gemini.
- **Nothing invented:** every value should come from the contractor's own data. Reviewers see these fields as the basis for the match explanation.

## 6. Example `contractors.csv`

```csv
talent_id,talent_name,location,standardized_headline,executive_summary,core_strengths,proof_points,main_industry,search_keywords,seniority,weekly_hours,rate_expectation,target_titles,contract,primary_profession,secondary_professions,years_experience,languages
TAL-CAN-001,Jordan Lee,"Toronto, ON",Bilingual Data Analyst (Power BI and SQL),"Analyst with 6 years building reporting for public-sector finance teams. Turns messy spreadsheets into dashboards managers use weekly.",Power BI|SQL|Excel|DAX,Cut month-end reporting from 5 days to 2|Built a KPI dashboard used by 40 managers,Public sector|Finance,dashboards|reporting|data visualisation,Intermediate,30,85,Data Analyst|BI Analyst|Reporting Analyst,true,data analysis and business intelligence,business analysis,6,en|fr
TAL-CAN-002,Sam Roy,"Québec, QC",Rédactrice et stratège de contenu,"Rédactrice bilingue, 10 ans en communication municipale et culturelle.",Rédaction|Révision|Stratégie de contenu|WordPress,Refonte du site d'une ville de 500 000 habitants,Secteur public|Culture,rédaction web|contenu,Senior,20,Industry Standard,Rédactrice|Content Strategist,true,content writing and editing,communications and public relations,10,fr|en
```

The names and details above are made up.
