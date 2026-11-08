"""Multilingual skills dictionary and extraction engine."""
from __future__ import annotations

import re

# Mapping: Canonical English Skill Name -> List of Regex/Keywords (English + Amharic)
SKILL_TAXONOMY: dict[str, list[str]] = {
    # Software, IT & Tech
    "Python": [r"\bpython\b", r"\bፓይተን\b"],
    "JavaScript": [r"\bjavascript\b", r"\bjs\b"],
    "TypeScript": [r"\btypescript\b", r"\bts\b"],
    "React": [r"\breact(?:\.js)?\b"],
    "Node.js": [r"\bnode(?:\.js)?\b"],
    "Next.js": [r"\bnext(?:\.js)?\b"],
    "HTML/CSS": [r"\bhtml\b", r"\bcss\b", r"\bhtml5\b", r"\bcss3\b"],
    "SQL": [r"\bsql\b"],
    "PostgreSQL": [r"\bpostgres(?:ql)?\b"],
    "MySQL": [r"\bmysql\b"],
    "MongoDB": [r"\bmongodb\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "AWS": [r"\baws\b", r"\bamazon web services\b"],
    "Azure": [r"\bazure\b"],
    "Flutter": [r"\bflutter\b"],
    "Dart": [r"\bdart\b"],
    "Android Development": [r"\bandroid\b"],
    "iOS Development": [r"\bios\b", r"\bswift\b"],
    "Java": [r"\bjava\b"],
    "C++": [r"\bc\+\+\b"],
    "C#": [r"\bc#\b", r"\bc-sharp\b", r"\b\.net\b"],
    "PHP": [r"\bphp\b"],
    "Laravel": [r"\blaravel\b"],
    "Django": [r"\bdjango\b"],
    "FastAPI": [r"\bfastapi\b"],
    "UI/UX Design": [r"\bui/ux\b", r"\bui\s*ux\b", r"\buser interface\b"],
    "Figma": [r"\bfigma\b"],
    "Linux": [r"\blinux\b", r"\bubuntu\b"],
    "Git": [r"\bgit\b", r"\bgithub\b", r"\bgitlab\b"],
    "Machine Learning": [r"\bmachine learning\b", r"\bml\b", r"\bai\b"],
    "Data Analysis": [r"\bdata analysis\b", r"\bdata analyst\b", r"\bየመረጃ ትንተና\b"],
    "Cybersecurity": [r"\bcyber\s*security\b", r"\binformation security\b"],
    "Network Administration": [r"\bnetworking\b", r"\bnetwork administrator\b", r"\bccna\b"],

    # Accounting, Finance & Banking
    "Accounting": [r"\baccounting\b", r"\baccountant\b", r"\bአካውንቲንግ\b", r"\bሂሳብ\b", r"\bየሂሳብ ባለሙያ\b"],
    "Auditing": [r"\baudit(?:ing|or)?\b", r"\bኦዲት\b", r"\bየኦዲት ባለሙያ\b"],
    "Financial Analysis": [r"\bfinancial analysis\b", r"\bfinancial analyst\b", r"\bፋይናንስ\b"],
    "IFRS": [r"\bifrs\b", r"\bአይ ኤፍ አር ኤስ\b"],
    "Peachtree": [r"\bpeachtree\b", r"\bፒችትሪ\b"],
    "QuickBooks": [r"\bquickbooks\b", r"\bክዊክ ቡክስ\b"],
    "Taxation": [r"\btax(?:ation)?\b", r"\bግብር\b", r"\bታክስ\b"],
    "Banking": [r"\bbanking\b", r"\bባንክ\b", r"\bባንኪንግ\b"],
    "Cashier": [r"\bcashier\b", r"\bካሼር\b", r"\bገንዘብ ያዥ\b"],
    "Payroll": [r"\bpayroll\b", r"\bየደመወዝ ክፍያ\b"],

    # Management, Business & Admin
    "Project Management": [r"\bproject management\b", r"\bproject manager\b", r"\bየፕሮጀክት አስተዳደር\b", r"\bpmp\b"],
    "Human Resources": [r"\bhuman resources?\b", r"\bhr\b", r"\bየሰው ኃይል\b"],
    "Administration": [r"\badministrat(?:ion|or|ive)\b", r"\bአስተዳደር\b", r"\bየቢሮ አስተዳደር\b"],
    "Procurement": [r"\bprocurement\b", r"\bግዢ\b", r"\bየግዢ ባለሙያ\b"],
    "Supply Chain": [r"\bsupply chain\b", r"\bአቅርቦት ሰንሰለት\b"],
    "Logistics": [r"\blogistics?\b", r"\bሎጅስቲክስ\b"],
    "Inventory Management": [r"\binventory\b", r"\bመጋዘን\b", r"\bስቶክ\b"],
    "Customer Service": [r"\bcustomer service\b", r"\bcustomer care\b", r"\bየደንበኞች አገልግሎት\b"],

    # Sales & Marketing
    "Sales": [r"\bsales\b", r"\bሽያጭ\b", r"\bየሽያጭ ባለሙያ\b"],
    "Marketing": [r"\bmarketing\b", r"\bማርኬቲንግ\b", r"\bገበያ ጥናት\b"],
    "Digital Marketing": [r"\bdigital marketing\b", r"\bዲጂታል ማርኬቲንግ\b", r"\bseo\b"],
    "Graphic Design": [r"\bgraphic design(?:er)?\b", r"\bphotoshop\b", r"\billustrator\b", r"\bግራፊክስ\b"],
    "Public Relations": [r"\bpublic relations\b", r"\bpr\b", r"\bየህዝብ ግንኙነት\b"],

    # Engineering & Architecture
    "Civil Engineering": [r"\bcivil engineering?\b", r"\bሲቪል ምህንድስና\b", r"\bኮንስትራክሽን\b"],
    "Structural Engineering": [r"\bstructural engineering\b", r"\bመዋቅራዊ ምህንድስና\b"],
    "Architecture": [r"\barchitect(?:ure)?\b", r"\bአርክቴክቸር\b"],
    "AutoCAD": [r"\bautocad\b", r"\bኦቶካድ\b"],
    "GIS": [r"\bgis\b", r"\bgeographic information\b", r"\bጂ አይ ኤስ\b"],
    "Electrical Engineering": [r"\belectrical engineering\b", r"\bኤሌክትሪካል ምህንድስና\b"],
    "Mechanical Engineering": [r"\bmechanical engineering\b", r"\bመካኒካል ምህንድስና\b"],

    # Health & Medicine
    "Nursing": [r"\bnurs(?:e|ing)\b", r"\bነርስ\b", r"\bነርሲንግ\b"],
    "Pharmacy": [r"\bpharmac(?:y|ist)\b", r"\bፋርማሲ\b", r"\bመድሃኒት\b"],
    "Medicine": [r"\bphysician\b", r"\bmedical doctor\b", r"\bሐኪም\b", r"\bዶክተር\b"],
    "Medical Laboratory": [r"\bmedical lab(?:oratory)?\b", r"\bየላቦራቶሪ\b"],
    "Public Health": [r"\bpublic health\b", r"\bየህዝብ ጤና\b"],
    "Midwifery": [r"\bmidwife(?:ry)?\b", r"\bአዋላጅ\b"],

    # Education, NGO & Social
    "Teaching": [r"\bteach(?:er|ing)\b", r"\blecturer\b", r"\bአስተማሪ\b", r"\bመምህር\b"],
    "Monitoring & Evaluation": [r"\bm&e\b", r"\bmonitoring and evaluation\b", r"\bክትትልና ግምገማ\b"],
    "Translation": [r"\btranslat(?:ion|or)\b", r"\binterprete?r\b", r"\bትርጉም\b"],

    # Operations & Trades
    "Driving": [r"\bdriver\b", r"\bdriving\b", r"\bሹፌር\b", r"\bመንጃ ፈቃድ\b"],
    "Security": [r"\bsecurity guard\b", r"\bጥበቃ\b", r"\bየጥበቃ ሰራተኛ\b"],
    "Electrician": [r"\belectrician\b", r"\bኤሌክትሪሺያን\b"],
}

# Compile all regex patterns once for fast extraction
_COMPILED_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (skill, [re.compile(p, re.IGNORECASE) for p in patterns])
    for skill, patterns in SKILL_TAXONOMY.items()
]


def extract_skills(text: str | None) -> list[str]:
    """Scan text (job title + description) and return canonical matched skill names."""
    if not text:
        return []

    matched: set[str] = set()
    for skill_name, patterns in _COMPILED_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                matched.add(skill_name)
                break

    return sorted(matched)
