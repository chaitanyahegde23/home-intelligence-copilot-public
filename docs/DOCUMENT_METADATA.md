# Automated document metadata

HIC-043 adds private, deterministic metadata understanding to native-text PDF extraction.

## Processing contract

After source-integrity verification and text extraction, classifier `household_document_rules:2`:

1. chooses a display title from a safe embedded PDF title, a strongly descriptive filename, the first plausible text heading, or the normalized filename stem;
2. scores bounded filename, title, and extracted-text signals for `identity`, `tax`, `financial`, `insurance`, `warranty`, `home`, `employment`, `immigration`, `legal`, `medical`, `education`, `correspondence`, and `receipt`;
3. leaves the type unclassified when the winning score is weak or too close to another type;
4. stores the suggestion, confidence, classifier identity, and non-sensitive evidence codes in `document_metadata_inferences`; and
5. applies suggestions only when that field has never been explicitly managed by the user.

Inference and extraction spans commit atomically. The classifier makes no network or OpenAI call.

## Provenance and overrides

`Document.title_source` and `Document.document_type_source` distinguish `automatic` values from `user` values. A user edit—including explicitly clearing a value—becomes authoritative. Extraction retries and later classifier/extractor versions may refresh automatic values but never replace user-managed values.

Evidence codes identify only the signal source and rule, for example `filename:passport` or `text:form_1040`; they never copy document text into metadata provenance. Full extracted text remains protected by the existing document access boundary.

## Limitations

- Classification is intentionally conservative; unfamiliar documents and close competing signals remain unclassified rather than being guessed.
- Native-text and local-OCR PDFs use this classifier after extraction.
- HIC-047 separately extracts conservative issuer, reference, subtype, document-date, and expiration-date facts; people, account numbers, tax years, and retention schedules remain unsupported.
- Existing completed documents receive inference when extraction is explicitly invoked again; the migration does not silently inspect stored private files.
- A confidence value describes rule strength, not a statistical probability.
