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
  few seconds apart. The adapter must back off and retry, and the daily run should keep to one
  request per article.

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
- **Terms of use: not settled.** The page asks users to cite the survey's article (Rovny et al. 2025,
  Electoral Studies 97, doi:10.1016/j.electstud.2025.102981). It states no licence, so whether scores
  may be republished in a public repository is the owner's call to make or to ask the survey team.
- **Rule until the owner decides:** leave `lr_score` empty with `lr_source: pending`. The file is not
  stored in this repository.

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
