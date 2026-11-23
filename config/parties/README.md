# Party files

One file per country: `config/parties/<CC>.yaml`. None are seeded, on purpose. Party lists and
left-right scores should be built from sources, not typed from memory.

## How to build one

1. Start from Europolls' mapping for the country, `config/party_mappings/<CC>.yaml` in
   https://github.com/gfrt0/europolls (MIT code, CC BY-SA 4.0 data). It carries Party Facts ids for
   about 97% of poll rows. Belgium is not covered there.
2. Keep the party short names exactly as pollsters and the source tables use them.
3. Fill `lr_score` from the Chapel Hill Expert Survey general left-right variable, latest wave that
   rates the party, joined on the Party Facts id. Set `lr_source` to the wave, for example `ches2024`.
4. For a party the survey lacks, leave `lr_score` empty with `lr_source: pending` and open a judgement
   proposal. Never guess a score in a commit.
5. Presidential candidates go in the same file with `type: candidate` and `party_id` pointing at the
   nominating party, whose score they inherit. An independent needs a hand-set score through a
   proposal.

See `_template.yaml` for the fields and `schemas/parties.schema.json` for the rules.
