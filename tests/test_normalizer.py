"""Unit tests for SIRALens Phase 2 Normalization Pipeline."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from normalizer.cleaners import clean_text, detect_language, strip_telegram_footer
from normalizer.dates import ethiopian_to_gregorian, gregorian_to_ethiopian, parse_date
from normalizer.dedup import make_dedup_key
from normalizer.extractors import (
    extract_apply_info,
    extract_education_level,
    extract_employer,
    extract_experience_years,
    extract_job_type,
    extract_location,
    extract_title,
    extract_work_mode,
)
from normalizer.pipeline import normalize_raw_capture
from normalizer.scam_detector import evaluate_risk
from normalizer.skills import extract_skills


class TestEthiopianDates:
    def test_meskerem_first_conversion(self):
        # Meskerem 1, 2017 EC is September 11, 2024 GC
        greg = ethiopian_to_gregorian(2017, 1, 1)
        assert greg == datetime.date(2024, 9, 11)

    def test_tikimt_conversion(self):
        # Tikimt 30, 2017 EC is November 9, 2024 GC
        greg = ethiopian_to_gregorian(2017, 2, 30)
        assert greg == datetime.date(2024, 11, 9)

    def test_genna_christmas_conversion(self):
        # Tahsas 29, 2017 EC is January 7, 2025 GC
        greg = ethiopian_to_gregorian(2017, 4, 29)
        assert greg == datetime.date(2025, 1, 7)

    def test_gregorian_to_ethiopian(self):
        ey, em, ed = gregorian_to_ethiopian(2024, 9, 11)
        assert (ey, em, ed) == (2017, 1, 1)

    def test_parse_amharic_month_text(self):
        dt = parse_date("ጥቅምት 30, 2017", reference_date=datetime.date(2024, 10, 1))
        assert dt == datetime.date(2024, 11, 9)

    def test_parse_gregorian_textual_date(self):
        dt = parse_date("November 18, 2026")
        assert dt == datetime.date(2026, 11, 18)

    def test_parse_iso_date(self):
        dt = parse_date("2026-12-05")
        assert dt == datetime.date(2026, 12, 5)

    def test_parse_relative_deadline(self):
        ref = datetime.date(2026, 11, 1)
        dt = parse_date("within 10 days", reference_date=ref)
        assert dt == datetime.date(2026, 11, 11)

        dt_am = parse_date("በ 7 ቀናት ውስጥ", reference_date=ref)
        assert dt_am == datetime.date(2026, 11, 8)


class TestCleanersAndLanguage:
    def test_clean_text_spacing(self):
        raw = "  Senior   Accountant \xa0\n\n\n\n  Lucy  Insurance  "
        cleaned = clean_text(raw)
        assert cleaned == "Senior Accountant\n\nLucy Insurance"

    def test_detect_language(self):
        assert detect_language("Senior Software Engineer required for Fintech company in Addis Ababa") == "en"
        assert detect_language("የስራ መደቡ መጠሪያ: የሂሳብ ባለሙያ ድርጅት: አቢሲኒያ ባንክ") == "am"
        assert detect_language("Job Title: የሂሳብ ባለሙያ Location: Addis Ababa አዲስ አበባ") == "mixed"

    def test_strip_telegram_footer(self):
        raw = "Job Vacancy\nPosition: Cashier\n\nJoin our Telegram channel: @abayjobs21 for more updates!"
        stripped = strip_telegram_footer(raw)
        assert "@abayjobs21" not in stripped
        assert "Position: Cashier" in stripped


class TestExtractors:
    def test_extract_title_and_employer(self):
        text = """
Job Title: Senior Underwriting Officer
Job Type: On-site - Permanent (Full-time)
Work Location: Addis Ababa, Ethiopia
Description:
Lucy Insurance S.C.
        """
        title = extract_title(text, {})
        assert title == "Senior Underwriting Officer"
        employer = extract_employer(text, {})
        assert employer == "Lucy Insurance S.C."

    def test_extract_amharic_title_and_employer(self):
        text = """
የስራ መደቡ: የሽያጭ ሰራተኛ
ድርጅት: አቢሲኒያ ባንክ
የስራ ቦታ: አዲስ አበባ
        """
        title = extract_title(text, {})
        assert "የሽያጭ ሰራተኛ" in title
        employer = extract_employer(text, {})
        assert "አቢሲኒያ ባንክ" in employer

    def test_extract_location_and_work_mode(self):
        text = "Location: Hawassa, Ethiopia. On-site full-time role."
        city, country = extract_location(text, {})
        assert city == "Hawassa"
        assert country == "ET"
        mode = extract_work_mode(text, {}, city)
        assert mode == "onsite"

    def test_extract_remote_work_mode(self):
        text = "This is a 100% remote job for software developers."
        mode = extract_work_mode(text, {}, None)
        assert mode == "remote"

    def test_extract_education_and_experience(self):
        text = "Requirements: BSc Degree in Computer Science with minimum 3 years of work experience."
        edu = extract_education_level(text)
        exp = extract_experience_years(text)
        assert edu == "Bachelor's"
        assert exp == 3

    def test_extract_fresh_graduate_experience(self):
        text = "Fresh graduate candidates with zero experience are encouraged to apply."
        exp = extract_experience_years(text)
        assert exp == 0


class TestSkills:
    def test_extract_skills_english(self):
        text = "We are seeking a Python developer experienced with React, SQL, and Docker."
        skills = extract_skills(text)
        assert "Python" in skills
        assert "React" in skills
        assert "SQL" in skills
        assert "Docker" in skills

    def test_extract_skills_amharic(self):
        text = "ድርጅታችን ልምድ ያለው የሂሳብ ባለሙያ እና ሹፌር ይፈልጋል::"
        skills = extract_skills(text)
        assert "Accounting" in skills
        assert "Driving" in skills


class TestScamDetection:
    def test_clean_job_has_zero_risk(self):
        text = "Commercial Bank of Ethiopia is hiring Junior IT officers. Apply through official portal."
        score, flags = evaluate_risk(text, employer="Commercial Bank of Ethiopia", apply_info="https://cbe.com.et")
        assert score == 0
        assert flags == []

    def test_upfront_fee_detection(self):
        text = "Urgent Cashier vacancy! Applicant must pay registration fee of 500 Birr before interview."
        score, flags = evaluate_risk(text)
        assert score >= 50
        assert "upfront_fee" in flags

    def test_suspicious_payment_detection(self):
        text = "ለስራው መመዝገቢያ 1000234567890 ብር አስገብታችሁ የደረሰኝ ፎቶ ላኩ::"
        score, flags = evaluate_risk(text)
        assert score >= 50
        assert "upfront_fee" in flags
        assert "suspicious_payment_account" in flags


class TestPipelineAndDedup:
    def test_pipeline_end_to_end(self):
        raw_text = """
Job Title: Senior Underwriting Officer
Job Type: On-site - Permanent (Full-time)
Work Location: Addis Ababa, Ethiopia
Deadline: November 18th, 2026
Description:
Lucy Insurance S.C.
Requires BA Degree in Management or Accounting with min 4 years experience.
Apply via email: info@lucyinsuranceet.com
        """
        job = normalize_raw_capture(
            raw_id=1,
            source_id=1,
            external_id="https://t.me/freelance_ethio/106551",
            url="https://t.me/freelance_ethio/106551",
            raw_text=raw_text,
            raw_meta={},
        )
        assert job.title == "Senior Underwriting Officer"
        assert job.employer_name == "Lucy Insurance S.C."
        assert job.location_city == "Addis Ababa"
        assert job.location_country == "ET"
        assert job.work_mode == "onsite"
        assert job.job_type == "full_time"
        assert job.education_level == "Bachelor's"
        assert job.experience_years_min == 4
        assert job.deadline == datetime.date(2026, 11, 18)
        assert "Accounting" in job.skills
        assert "info@lucyinsuranceet.com" in (job.apply_info or "")
        assert job.risk_score == 0

    def test_dedup_keys(self):
        k1 = make_dedup_key("Lucy Insurance S.C.", "Senior Underwriting Officer", "2026-11-18")
        k2 = make_dedup_key("lucy insurance s.c.", "senior underwriting officer", "2026-11-18")
        assert k1 == k2
