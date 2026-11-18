---
name: website-conventions
description: Rules every website follows: light and dark mode with the shared theme and switch,
  imprint, privacy and terms pages with fixed routes and locale redirects, a footer on every
  page, and nothing built that the shared web library provides. Use when building, extending or
  reviewing a website, a landing page or its legal pages. Trigger phrases: new website, landing
  page, imprint, privacy page, Impressum, Datenschutz, AGB, Webseite bauen, Webseite pruefen.
---

# Website conventions

One rule set for every website, so each site is built and reviewed the same way.

## When to use

- Building a website or a landing page.
- Adding or changing an imprint, privacy or terms page.
- Reviewing a website against the baseline.
- A site needs a feature the shared web library might already offer.

## Rules

### Shared web library

- A site implements nothing the shared web library provides or will provide.
- A missing piece is an issue in the shared web library first. The site waits or uses the
  released version. It never keeps a private copy.
- The redirect set, the page shells and the footer links come from the library, not from the
  site.
- The library never ships legal texts and never carries a brand colour.

### Theme

- Every site offers light and dark mode with the shared theme and the theme switch.
- The palette is the site's own.

### Legal pages

- Every site has its own imprint, privacy statement and terms, written for that site.
- The texts live in the site's repository. They are never shared between sites.
- The owner reviews every text. The texts are not legal advice.
- Pages exist in German and English. The German text is binding.
- The terms page exists only for a site that sells something. Otherwise `/terms` and `/agb`
  are both left out.
- The imprint has no dispute resolution section. No arbitration statement, no online dispute
  platform link.

### Routes

- English names: `/imprint`, `/privacy`, `/terms`.
- German aliases: `/impressum`, `/datenschutz`, `/datenschutzerklaerung`, `/agb`.
- Each unprefixed path and each alias redirects server side to the page of the matching locale,
  `/de/...` or `/en/...`. Example: `/impressum` to `/de/imprint`.
- The locale comes from the visitor's choice, then the `Accept-Language` header, then the site
  default.
- A footer links the pages on every page.

### Text structure

- Treat this as a hint for the outline. Write the sentences from the site itself.
- Imprint: short. Provider block, contact, VAT ID where the provider has one.
- Privacy: a short plain language lead, then numbered chapters.
- Chapters: at a glance, hosting, general notes and mandatory information, data collection on
  this website.
- Data collection lists only what the site really does. Per item: what is stored, why, the
  legal basis and how long.
- Social media gets a chapter only if it is embedded or linked.
- Terms: numbered clauses.

## Steps

### Build a site

1. Check that the released shared web library supports the routes, the theme and the footer.
2. File a library issue for every gap. Wait or pin the released version.
3. Register the routes once, through the library.
4. Read the site's real features and config values: cookies, analytics, forms, hosting, payments.
5. Write the imprint and privacy text from those facts, in German and English.
6. Write the terms only if the site sells something.
7. Run the repository's verify command.
8. List for the owner every text to review and every fact the site could not supply.

### Review a site

1. Light and dark mode with the shared theme and switch work.
2. All seven paths redirect server side to the right locale page, or the terms paths are
   absent on a site that sells nothing.
3. The locale order is visitor choice, header, site default.
4. German and English pages exist and the German text is binding.
5. The footer links the pages on every page.
6. The imprint has no dispute resolution section.
7. The texts are the site's own and match what the site really does.
8. No code copies a shared library feature.

## Guardrails

- Never copy a legal text from another site or from the library.
- Never claim a text is legal advice or final before the owner reviewed it.
- Never invent a provider detail, a VAT ID or a retention period. Ask the owner.
- Never keep a private copy of a library feature to avoid waiting.
- Never add a dispute resolution section to an imprint.

## References

- `repo-conventions` for the repository layout.
- `writing-style` for the wording of the texts.
