# School Ambassador — Non-Technical Staff Guide

Welcome to the **AI School Ambassador** guide. This document explains how school staff can update school information quickly without needing programming knowledge.

---

## How to Update School Information

All information the robot ambassador knows is stored as markdown text files in the `kb/` folder:
- **`kb/school/`**: Academic curriculum, admissions, activities, calendar & timings, facilities, safety, student life, staff directory, fee structure, FAQs.
- **`kb/partnership/`**: Weguide partnership details, robotics programs, kiosks, scope, and technical contacts.

### 1. Document Format & Guidelines

Each section must follow this structure:
```markdown
# Section Title (One H1 per file)

## Topic or Question Name (H2 per topic)

Questions this answers: What time does school start? | When do gates open? | How late can my child arrive?

Write factual information in plain, spoken English.
- Write times as "7:30 AM" or "8:00 AM".
- Write dates in words, such as "April 10th" or "March 31st".
- Spell out units and currency, such as "50 rupees per day" or "10 percent".
```

> **Important**:
> - **Never** include private phone numbers, home addresses, or confidential student records.
> - Always include the `Questions this answers:` line under each `##` heading with 2 to 4 natural questions parents or visitors would ask aloud.

---

## 2. Ingesting & Applying Changes

After editing any file, apply your changes from the terminal:

1. **Verify with a Dry-Run Report (Safe Check)**:
   ```bash
   python ingest.py --report
   ```
   This will show total chunks, word counts, and check that no questions lines are missing.

2. **Index Your Changes**:
   ```bash
   python ingest.py
   ```
   Ingestion is incremental and only updates modified files.

3. **Rebuild from Scratch (If Re-structuring)**:
   ```bash
   python ingest.py --rebuild
   ```

4. **Calibrate Threshold (Optional)**:
   ```bash
   python calibrate_threshold.py --apply
   ```

---

## 3. Rollback Instructions

If an edit causes unexpected behavior:
1. Copy the original files back from `kb_backup/` to `kb/`.
2. Run `python ingest.py --rebuild`.

---

## 4. Emergency Override (Taking the Kiosk Offline)

If maintenance is required or you need to temporarily take the kiosk offline:
- Create a file named `offline.flag` in the `school-ambassador/` folder, or
- Close the kiosk application window.
The kiosk will gracefully pause interactions until the flag is removed.
