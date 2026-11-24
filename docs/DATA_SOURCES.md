# Data sources

What feeds the dashboard, how to reach it, what the licence requires, and what nobody has checked yet.
Researched on 23 Nov 2026. Re-check anything marked unverified before relying on it.

## In use

### English Wikipedia polling articles (backbone)

- **Covers:** all 18 national contests and most polled sub-national ones.
- **Access:** MediaWiki Action API. Fetch the article's current revision id first, then the parsed
  tables for that exact revision, and store the revision id in `source_rev` on every row.
- **Licence:** CC BY-SA 4.0. Attribution and share-alike apply to the derived dataset.
- **Shape:** one or more wikitables per article. Layouts differ by article and change without notice.
  Articles for long cycles are often split by year. Some small contests keep their polling inside the
  election article rather than a dedicated polling article.
- **Known hard cases:** Belgium (separate regional sub-tables), France presidential (many candidate
  line-ups per poll, plus second-round match-ups), the Netherlands (seats, not percentages), the
  Scottish Parliament (constituency and list votes).
- **Etiquette:** set a descriptive User-Agent with a contact address; one request per article per run;
  no parallel bursts.
- **Checked on 23 Nov 2026:** every Wikipedia title in `config/sources.yaml` was resolved through the
  API. Two seeded titles were redirects to a section of an election article and were replaced by the
  article they point to (French legislative, Senedd). Table layouts are not inspected yet.
- **Rate limits:** the API answered several single requests with HTTP 429 during the check, even a
  few seconds apart. The adapter backs off and retries, and makes two requests per article per run:
  one API query for the current revision id, then `index.php?oldid=<id>&action=render` for that
  revision's content, which was throttled less often than `action=parse`.
- **What the adapter reads (Phase 1):** the rendered page is cut down to headings, wikitables and
  reference lists, then each table selected by the contest's `selector` is read as a grid with spans
  expanded. Year-less dates take the year from the heading above the table. One figure spanning several
  party columns is a joint list and maps to an alliance row in the party file. A row whose pollster cell
  names an election is the official result and goes to `data/results.csv`. A table without a date
  column, a pollster column or two party columns fails the pull.
- **Phase 2 additions:** a table can be read in seats (Netherlands), as named regional panels of one
  contest (Belgium: Flanders, Wallonia, Brussels), with the publication link in a Ref or Sources
  column, with a Method column, and with the year printed on only some rows. Column groups headed
  Coalitions or Blocs are never read.
- **Articles found by search, not by title pattern:** Belgium's current article is "Opinion polling
  for the 2029 Belgian elections"; the "next Belgian federal election" titles redirect elsewhere.
  The Czech "next parliamentary election" polling title redirects to the 2025 article; the current
  tables sit in "Next Czech parliamentary election".
- **No source for five presidential contests.** Austria, Portugal, Ireland, Poland and Finland have no
  polling tables on Wikipedia yet, so their headlines read "not yet polled". The Czech presidential
  article has first-round tables, but respondents could name several candidates and the figures sum
  to about 135, so it is not read as voting intention.
- **Not read yet:** seat figures printed under vote shares (Spain, Denmark, Norway, Greece, Czechia),
  and polling for Spain before 2025, which sits in a separate article.

### Europolls (reuse of code and mappings, not of output)

- https://github.com/gfrt0/europolls — a Wikipedia-derived database of polls for 30 countries.
- **Licence:** code MIT, data CC BY-SA 4.0 (read from the repository's `LICENSE` and `LICENSE-DATA`).
- **Why it matters:** it already solves most of the parsing, and its `config/party_mappings/<CC>.yaml`
  files map party labels to Party Facts ids (about 97% of poll rows), which is the join key for
  left-right scores. It pins revisions and keeps each poll's publication link.
- **Gaps:** no Belgium; no sub-national contests; the French presidential series ends in 2022; only
  Italy has been validated against an official register. Its scheduled build runs weekly.
- **How to use it:** read its parser and `docs/ADDING_A_COUNTRY.md` before writing ours; start party
  files from its mappings; credit it in `NOTICE-DATA.md`. Do not make the daily pipeline depend on its
  published output.

### DAWUM (Germany)

- https://dawum.de/API/ — polls for the Bundestag and all 16 Landtage since 2017.
- **Access:** one JSON file at `https://api.dawum.de/`; a compact file with only the newest poll per
  institute and parliament at `https://api.dawum.de/newest_surveys.json`; a plain-text timestamp at
  `https://api.dawum.de/last_update.txt` to check whether a stored copy is current.
- **Fields:** parliament, institute, client, party results, publication date, survey period, number of
  respondents, survey method.
- **Licence:** ODC Open Database License (ODbL). Works that use the database must name and link
  dawum.de and the licence; a derived database that is published is itself under ODbL. DAWUM suggests
  the wording "Daten von dawum.de (Open Database License (ODbL))".
- **Checked on 23 Nov 2026:** the full file has seven top-level blocks: `Database`, `Parliaments`,
  `Institutes`, `Taskers`, `Methods`, `Parties`, `Surveys`. `Database` carries the licence and
  `Last_Update`. A survey has `Date` (publication), `Survey_Period` (`Date_Start`, `Date_End`),
  `Surveyed_Persons`, `Parliament_ID`, `Institute_ID`, `Tasker_ID`, `Method_ID` and `Results`
  (party id to percentage). All ids are strings. The file held 4,017 surveys, 22 institutes and
  18 parliaments: the Bundestag, the 16 Landtage and the European Parliament.
- **Parliament ids are still read at run time**, matched on the `Shortcut` field, and not stored in
  configuration. One shortcut differs from the Land's name: `Nordrhein-Westfalen (NRW)`.

### SwedishPolls (Sweden)

- https://github.com/MansMeg/SwedishPolls — `Data/Polls.csv`, updated on 23 Nov 2026 when inspected.
- **Columns:** `PublYearMonth, Company, M, L, C, KD, S, V, MP, SD, FI, Uncertain, n, PublDate,
  collectPeriodFrom, collectPeriodTo, approxPeriod, house`. Missing values are the literal `NA`.
- **Licence:** the README carries MIT and CC0 badges.
- **Notes from its README:** `house` is the pollster's current name and is the one to use; `n` is the
  number of respondents with a party preference; some Ipsos rows were normalised to sum to 100.

### Chapel Hill Expert Survey (left-right scores)

- **Checked on 23 Nov 2026:** https://www.chesdata.eu/ches-europe links the 2024 wave as CSV and Stata
  files (`CHES_2024_final_v2.csv`) with a codebook, hosted as GitHub release assets of
  `chesdata/chesdata.github.io`. The CSV has 279 parties in 31 countries and 53 columns. The general
  left-right variable is `lrgen`, 0 to 10, with no missing values. Norway and the UK are both in it,
  as are all 16 other countries here.
- **Party ids:** the file keys parties by CHES's own numeric `party_id` and a numeric `country`. It
  has no Party Facts column, so the join to Party Facts ids needs Party Facts' own linking table.
  That table has not been checked yet.
- **Terms of use.** The page asks users to cite the survey's article (Rovny et al. 2025, Electoral
  Studies 97, doi:10.1016/j.electstud.2025.102981) and states no licence. The owner decided on
  23 Nov 2026 to republish each party's general left-right score with that citation. The survey's
  file is still not stored in this repository; only the one score per party is, in `config/parties/`.
- **How scores get in:** `tools/propose_lr_scores.py` joins the 2024 file to the party files through
  Party Facts' external-parties table (https://partyfacts.herokuapp.com/download/external-parties-csv/,
  dataset `ches`). Party Facts has not linked the 2024 wave's new parties, so the tool also matches a
  party when the survey prints the same label for it in the same country. Scores reach the party
  files only through a judgement-proposal pull request.

## Considered and not used

| Source | Why not |
| --- | --- |
| Europe Elects | Now by request with an institutional email, and redistribution is not permitted, according to the terms quoted in search results. Their page blocked automated reading, so read the terms yourself before ever reconsidering. The old public mirror (`filipvanlaenen/eopaod`) has not been updated since 30 Mar 2024, and its successor repository asks for credentials |
| PolitPro API | Paid (EUR 49 a week for raw data when checked), terms set per use. It does cover Austrian, Belgian and German regional parliaments. The fallback if open data proves too thin; needs AC's decision |
| Politico Poll of Polls | Charts only; no data download |

## For spot checks, not ingestion

- Italy: the government's poll register at sondaggipoliticoelettorali.it. Europolls validated its
  Italian scrape against a GitHub mirror of it (`ondata/liberiamoli-tutti`).
- France: the Commission des sondages publishes a technical notice for each poll.

## Calendar sources

| Source | Used for |
| --- | --- |
| Federal Returning Officer, `bundeswahlleiterin.de/service/wahltermine.html` | German federal and state dates |
| Council of Europe Congress, yearly local and regional elections calendar | Sub-national dates across Europe |
| European Committee of the Regions, elections calendar 2024–2029 | National, regional and local dates in EU members |
| Congressional Research Service fact sheet R46858 | Last and next parliamentary and presidential dates |
| National electoral authorities | The final word on any date |

Each row of `config/contests.yaml` records which of these it came from and whether the page was opened.

## A constraint to remember

From Claude's cloud workspace, `git` reached public GitHub repositories but ordinary web requests from
the shell were refused, and the web-fetch tool returns a summary of a page rather than its raw tables.
So bulk fetching runs in GitHub Actions. A Claude session can still read sources that live in public
GitHub repositories (Europolls, SwedishPolls) by cloning them.
