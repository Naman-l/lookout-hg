"""The cast of the HG dummy dataset: projects, people, vendors, materials, rates.

Project names, verticals, material names, units and the rates of the Oct-Dec requirement sheets are H.G. Infra's own, taken from the SCM
departmental review's source sheets; plant codes and SAP plant names are HG's own, taken from its MB51 exports for FY25-26 and FY26-27. Every
person outside the SCM organogram, vendor, contact, e-mail address, GSTIN and amount that is not a sheet rate is invented. The SCM team is HG's own,
from its organogram; no other real person's or company's name is used.
"""
from __future__ import annotations

INTERNAL_DOMAIN = "hginfra.example"
LOOKALIKE_INTERNAL = "hglnfra.example"      # "l" for "i": folds to the company's own domain

# ------------------------------------------------------------------------------------------------------------------- the SCM team
# HG's own SCM (material) organogram, as the user supplied it on 21 Oct 2026 (dummy_data/hg_organogram.csv, written to data/sheets as it is): the
# Sr. Vice President who heads SCM, the GMs, AGM and Manager who report to him, and their teams. Names, designations and desks are HG's; SAP users,
# purchasing groups, e-mail addresses and DoA limits are invented.
ORGANOGRAM = "hg_organogram.csv"
# id (first name), full name, initials, role, purchasing groups, verticals, SAP user, signs up to (INR, None = no limit), countersigns
TEAM = [
    ("Satish", "Satish Kumar Sharma", "SS", "Head of SCM, Sr. Vice President", ["H00"], ["roads", "railway", "bess", "solar", "td"], "SKSHARMA", None, True),
    ("ShreeDutt", "Shree Dutt Anand", "SA", "GM SCM, mechanical spares and petroleum", ["P00"], ["roads"], "SDANAND", 5_00_00_000, False),
    ("Varun", "Varun Joshi", "VJ", "GM SCM, aggregate, cement, shuttering, consumables and logistics", ["A00"], ["roads", "railway"], "VJOSHI", 5_00_00_000, False),
    ("Sambhav", "Sambhav Kumar", "SK", "GM SCM, solar, transformers, railway, BESS and lines", ["T01"], ["railway", "bess", "solar", "td"], "SKUMAR", 5_00_00_000, False),
    ("Urvik", "Urvik Patel", "UP", "AGM SCM, TMT and steel, structures and containers", ["U01"], ["roads", "bess", "solar"], "UPATEL", 5_00_00_000, False),
    ("Gautam", "Gautam Jha", "GJ", "Manager SCM, site NOA approvals of services", ["W01"], ["railway", "roads"], "GJHA", 1_00_00_000, False),
    ("Mohan", "Mohan Bahadur", "MB", "Manager, petroleum products (bitumen)", ["P01"], ["roads"], "MBAHADUR", 1_00_00_000, False),
    ("Sudeep", "Sudeep Singh", "SS", "AM, MIS (fund requirement, payment tracker)", ["M01"], [], "SSINGH", 0, False),
    ("Harish", "Harish Kumar", "HK", "DM, petroleum documentation and HSD retailers", ["P02"], ["roads"], "HKUMAR", 1_00_00_000, False),
    ("Lokesh", "Lokesh Yadav", "LY", "Supervisor, local market runner", [], [], "LYADAV", 0, False),
    ("Jitender", "Jitender Swami", "JS", "AM, aggregate (Dhule, Aurangabad, Gaya, Tumkur, JH-10, JH-13)", ["A01"], ["roads", "railway"], "JSWAMI", 1_00_00_000, False),
    ("Neeraj", "Neeraj", "NE", "Sr. Exc., aggregate and scrap sale (Ganga, NDLS, Anuppur, Thane)", ["A02"], ["roads", "railway"], "NEERAJ", 25_00_000, False),
    ("Govind", "Govind Gupta", "GG", "AM, cement, fly ash, GGBS and admixture", ["C01"], ["roads", "railway"], "GGUPTA", 1_00_00_000, False),
    ("Ishan", "Ishan Derashri", "ID", "DM, bearings, expansion joints, pre-stressing, slope protection", ["E01"], ["roads"], "IDERASHRI", 1_00_00_000, False),
    ("Ankesh", "Ankesh Jha", "AJ", "Sr. Engg., shuttering, hume pipe and engineering items", ["E02"], ["roads", "railway"], "AJHA", 25_00_000, False),
    ("Jitendra", "Jitendra Shekhawat", "JS", "Manager, IT and electrical, lab and survey, MIS-TMT", ["G01"], [], "JSHEKHAWAT", 1_00_00_000, False),
    ("Kanhaiya", "Kanhaiya Khoda", "KK", "Exc., lab, safety and general consumables", ["G02"], [], "KKHODA", 25_00_000, False),
    ("Jagdish", "Jagdish Vyas", "JV", "AM, logistics (machines and equipment)", ["X01"], ["railway", "roads"], "JVYAS", 1_00_00_000, False),
    ("Rajesh", "Rajesh", "RA", "Sr. Exc., logistics (machines and equipment)", [], [], "RAJESH", 25_00_000, False),
    ("Rohit", "Rohit Jain", "RJ", "AM, railway S&T", ["L01"], ["railway"], "RJAIN", 1_00_00_000, False),
    ("Vishnu", "Vishnu Mudgal", "VM", "AM, OHE, BESS, solar inverters and TBCB lines", ["L03"], ["railway", "bess", "solar", "td"], "VMUDGAL", 1_00_00_000, False),
    ("Deepanshu", "Deepanshu Jain", "DJ", "Sr. Engg., P-Way, cables and transformers", ["L02"], ["railway", "bess", "solar", "td"], "DJAIN", 25_00_000, False),
    ("Harigraraj", "Harigraraj D", "HD", "MT, solar", ["N01"], ["solar"], "HARIGRARAJ", 25_00_000, False),
    ("Shubham", "Shubham Sharma", "SH", "AM, TMT and structural steel", ["S01"], ["roads", "railway"], "SSHARMA", 1_00_00_000, False),
    ("Ankit", "Ankit Solanki", "AS", "Jr. Exc., SCM accounts, ageing and PR release", [], [], "ASOLANKI", 0, False),
]
REPORTS_TO = {   # member -> the member they report to, as the organogram draws it (the recipe reads the sheet itself; the generator needs it for CS approvers)
    "ShreeDutt": "Satish", "Varun": "Satish", "Sambhav": "Satish", "Urvik": "Satish", "Gautam": "Satish",
    "Mohan": "ShreeDutt", "Sudeep": "ShreeDutt", "Harish": "ShreeDutt", "Lokesh": "ShreeDutt",
    "Jitender": "Varun", "Neeraj": "Varun", "Govind": "Varun", "Ishan": "Varun", "Ankesh": "Varun", "Jitendra": "Varun", "Kanhaiya": "Varun",
    "Jagdish": "Varun", "Rajesh": "Varun",
    "Rohit": "Sambhav", "Vishnu": "Sambhav", "Deepanshu": "Sambhav", "Harigraraj": "Sambhav",
    "Shubham": "Urvik", "Ankit": "Urvik",
}
PURCH_GROUPS = {   # SAP purchasing group -> description (T024 export): one desk each, as the organogram splits the work
    "H00": "HO-SCM Head", "P00": "HO-Mech. Spares & Equipment", "P01": "HO-Petroleum (Bitumen)", "P02": "HO-Petroleum (HSD & Retail)",
    "M01": "HO-SCM MIS", "A00": "HO-Aggregate (Other Sites)", "A01": "HO-Aggregate Desk 1", "A02": "HO-Aggregate Desk 2 & Scrap",
    "C01": "HO-Cement, Fly Ash & Admixture", "E01": "HO-Bearing, Pre-stress & Slope", "E02": "HO-Shuttering & Hume Pipe", "G01": "HO-IT & Electrical",
    "G02": "HO-Lab, Safety & Gen. Consumables", "X01": "HO-Logistics", "L01": "HO-Railway S&T", "L02": "HO-P-Way, Cables & Transformers",
    "L03": "HO-OHE, BESS & Lines", "N01": "HO-Solar", "T01": "HO-Switchgear & T&D", "U01": "HO-Solar Structure & Containers",
    "S01": "HO-TMT & Structural Steel", "W01": "HO-Site Services NOA",
}
# Which desk buys what: a material group (or one material) -> purchasing group. Aggregate goes by site, as the organogram lists each buyer's sites;
# sites it names for nobody stay on the GM's own desk (A00).
AGGREGATE_GROUPS = {"AGGREGATE", "DUST", "WMM", "GSB", "BOULDER", "BALLAST", "BLANKET", "SAND"}
AGGREGATE_SITES = {"A01": {"dhule", "aurangabad", "gaya", "tumkur", "jh10", "jh13"}, "A02": {"gew05", "ndls", "anuppur", "thane"}}
DESK_OF_GROUP = {
    "CEMENT": "C01", "GGBS": "C01", "FLYASH": "C01", "MICROSILICA": "C01", "ADMIXTURE": "C01",
    "BEARING": "E01", "EXPJOINT": "E01", "HTSTRAND": "E01", "BARRIER": "E01", "GEOSYN": "E01", "PIPE": "E02", "MISC": "E02",
    "TMT": "S01", "STRUCT": "S01", "BITUMEN": "P01", "EMULSION": "P01", "HSD": "P02", "DG": "P00",
    "RLY-SNT": "L01", "RLY-PWAY": "L02", "CABLE": "L02", "ELE-TFR": "L02",
    "RLY-OHEMAST": "L03", "RLY-OHEWIRE": "L03", "RLY-INSUL": "L03", "BESS": "L03", "TL-TOWER": "L03", "TL-COND": "L03", "TL-INSUL": "L03",
    "ELE-SWG": "T01", "ELE-MISC": "T01", "SOLAR": "N01",
}
DESK_OF_MATERIAL = {"31000710": "L03", "31000720": "U01", "31000610": "U01", "41000810": "X01", "41000820": "W01"}
# First names the first cast used: invented people never take them, as before, so every random draw keeps its place.
FIRST_CAST = {"Rajeev", "Anita", "Vikram", "Sanjay", "Meera", "Arjun", "Farhan", "Pooja", "Rohit", "Neha"}

# People outside SCM: senders and recipients of notes, never users. function -> (name, title, email local part)
FUNCTIONS = {
    "finance_treasury": ("Sudhir Bansal", "Manager, Treasury (LC and bank guarantees)", "sudhir.bansal"),
    "finance_funds": ("Kirti Mehta", "Manager, Fund Planning, Finance", "kirti.mehta"),
    "qa": ("Hemant Rawat", "Head, QA/QC and Inspection", "hemant.rawat"),
    "qa_inspection": ("Divya Pillai", "Inspection Engineer, QA", "divya.pillai"),
    "vendor_master": ("Ashish Goyal", "Vendor Master Desk, Finance", "ashish.goyal"),
    "md_office": ("Office of the Managing Director", "Managing Director's Office", "md.office"),
}

_FIRST = ["Ajay", "Alok", "Anand", "Ashok", "Bharat", "Chetan", "Devendra", "Dinesh", "Ganesh", "Girish", "Harish", "Jitendra", "Kailash",
          "Kamal", "Lalit", "Mahesh", "Manoj", "Mukesh", "Naresh", "Nitin", "Pankaj", "Pradeep", "Rakesh", "Ramesh", "Sachin", "Sandeep",
          "Santosh", "Shailesh", "Subhash", "Tarun", "Umesh", "Vinod", "Yogesh", "Abhishek", "Ankit", "Kunal", "Mayank", "Nikhil", "Prateek",
          "Saurabh", "Tushar", "Varun", "Vivek", "Swati", "Priyanka", "Shweta", "Rashmi", "Sneha", "Pallavi", "Aarti", "Bhavna", "Jyoti",
          "Komal", "Lata", "Madhuri", "Nidhi", "Preeti", "Seema", "Usha", "Vandana"]
_LAST = ["Gupta", "Jain", "Mehrotra", "Shah", "Pandey", "Dubey", "Tripathi", "Srivastava", "Chaturvedi", "Bhardwaj", "Negi", "Bisht",
         "Thakur", "Chopra", "Kapoor", "Khanna", "Arora", "Sethi", "Mittal", "Bajaj", "Dutta", "Bose", "Ghosh", "Sen", "Mohanty", "Panda",
         "Reddy", "Naidu", "Kamath", "Hegde", "Shetty", "Gowda", "Desai", "Pawar", "Shinde", "Jadhav", "Gaikwad", "Kale", "Bhosale", "Solanki",
         "Parmar", "Rathod", "Rajput", "Tiwari", "Mishra", "Dwivedi", "Awasthi", "Saini", "Dhillon", "Grewal"]

# ------------------------------------------------------------------------------------------------------------------- projects
# id, name (as the requirement sheets print it), vertical, stage, state, district, plants, tracking code, start month, SAP plant long name,
# work fronts: (name, material groups it consumes). Plants and SAP plant names are as HG's MB51 exports print them (FY26-27, else FY25-26); a
# project in neither export has no plant here, and so no SAP records.
_RD_FRONTS = [("Earthwork and GSB", ["GSB", "SAND", "AGGREGATE", "BOULDER"]), ("WMM and base", ["AGGREGATE", "DUST", "WMM"]),
              ("Bituminous courses", ["BITUMEN", "EMULSION", "AGGREGATE", "DUST", "HSD"]), ("Structures", ["CEMENT", "GGBS", "FLYASH", "TMT", "HTSTRAND", "ADMIXTURE", "BEARING", "EXPJOINT", "SAND"])]
_RL_FRONTS = [("Track (P-Way)", ["BALLAST", "RLY-PWAY", "BLANKET"]), ("OHE mast erection", ["RLY-OHEMAST", "CEMENT", "TMT", "AGGREGATE"]),
              ("OHE wiring", ["RLY-OHEWIRE", "RLY-INSUL"]), ("S&T", ["RLY-SNT", "CABLE"]), ("Civil and bridges", ["AGGREGATE", "SAND", "CEMENT", "TMT", "BLANKET", "GSB", "DUST"])]
_BS_FRONTS = [("Containers and PCS", ["BESS"]), ("Substation (GIS and transformers)", ["ELE-TFR", "ELE-SWG"]), ("Cabling", ["CABLE"]), ("Civil", ["CEMENT", "TMT", "AGGREGATE"])]
_SL_FRONTS = [("Module mounting", ["SOLAR"]), ("Inverters and transformers", ["SOLAR", "ELE-TFR"]), ("Cabling", ["CABLE"]), ("O&M spares", ["SOLAR", "ELE-SWG"])]
_TD_FRONTS = [("Tower erection", ["TL-TOWER", "CEMENT", "TMT"]), ("Stringing", ["TL-COND", "TL-INSUL"]), ("Substation", ["ELE-TFR", "ELE-SWG"])]

PROJECTS = [
    # roads, newly started
    ("tumkur", "Tumkur", "roads", "new", "Karnataka", "Tumakuru", ["1138"], "RD-TUMKUR", "2026-01", "Neelmangala-Tumkur", _RD_FRONTS),
    ("jh10", "JH-10", "roads", "new", "Jharkhand", "Ranchi", ["1142"], "RD-JH10", "2025-12", "Jharkhand Pkg-10", _RD_FRONTS),
    ("jh13", "JH-13", "roads", "new", "Jharkhand", "Khunti", ["1143"], "RD-JH13", "2026-02", "Jharkhand Pkg-13", _RD_FRONTS),
    ("jec", "JEC", "roads", "new", "Jharkhand", "East Singhbhum", ["1147"], "RD-JEC", "2026-03", "Jamshedpur Elevated Corridor", _RD_FRONTS),
    ("tirupati", "Tirupati", "roads", "new", "Andhra Pradesh", "Tirupati", ["1148"], "RD-TIRUP", "2025-11", "Chennai Tirupati Pkg-2", _RD_FRONTS),
    ("ayodhya", "Ayodhya", "roads", "new", "Uttar Pradesh", "Ayodhya", ["1151"], "RD-AYODH", "2026-02", "NH-227B Bahuvan Ayodhya UP", _RD_FRONTS),
    ("narol", "Narol", "roads", "new", "Gujarat", "Ahmedabad", ["1152"], "RD-NAROL", "2026-04", "Narol Jn to Sarkhej Jn-Aho-GJ", _RD_FRONTS),
    ("pune_shirur", "Pune-Shirur", "roads", "new", "Maharashtra", "Pune", [], "RD-PUNESH", "2026-05", "", _RD_FRONTS),
    # roads, nearing completion
    ("kd01", "KD-01", "roads", "nearing_completion", "Telangana", "Khammam", ["1131"], "RD-KD01", "2024-04", "Khammam-Devarapalle (KD-1)", _RD_FRONTS),
    ("kd02", "KD-02", "roads", "nearing_completion", "Telangana", "Khammam", ["1132"], "RD-KD02", "2024-04", "Khammam Devarapalle (KD-2)", _RD_FRONTS),
    ("ap01", "AP-01", "roads", "nearing_completion", "Andhra Pradesh", "Krishna", ["1133"], "RD-AP01", "2024-06", "Raipur Visakhapatnam (RVAP-1)", _RD_FRONTS),
    ("karnal", "Karnal", "roads", "nearing_completion", "Haryana", "Karnal", ["1141"], "RD-KARNAL", "2024-02", "Karnal Ring Road", _RD_FRONTS),
    ("gew05", "GEW-05", "roads", "nearing_completion", "Uttar Pradesh", "Unnao", ["1145"], "RD-GEW05", "2024-01", "Ganga Expressway Pkg-5", _RD_FRONTS),
    # railway (DLF is a highway plant in SAP; SCM plans it with the railway jobs, as the railway sheet does)
    ("rvnl", "RVNL", "railway", "running", "Chhattisgarh", "Bilaspur", ["1902"], "RL-RVNL", "2024-09", "Bilaspur RVNL", _RL_FRONTS),
    ("kanpur", "Kanpur", "railway", "running", "Uttar Pradesh", "Kanpur Nagar", ["1903"], "RL-KANPUR", "2024-11", "Kanpur Station Modification", _RL_FRONTS),
    ("dhule", "Dhule", "railway", "running", "Maharashtra", "Dhule", ["1904"], "RL-DHULE", "2025-02", "DHULE-NARDANA RAILWAY", _RL_FRONTS),
    ("aurangabad", "Aurangabad", "railway", "running", "Maharashtra", "Chhatrapati Sambhajinagar", ["1905"], "RL-AURANG", "2025-01", "KARANJGAON_AURANGABAD_RVNL_PK9", _RL_FRONTS),
    ("gaya", "Gaya", "railway", "running", "Bihar", "Gaya", ["1906"], "RL-GAYA", "2025-05", "GAYA-SON NAGAR-RVNL", _RL_FRONTS),
    ("ndls", "NDLS", "railway", "running", "Delhi", "New Delhi", ["1907"], "RL-NDLS", "2025-03", "DELHI STATION MODIFICATION", _RL_FRONTS),
    ("thane", "Thane", "railway", "running", "Maharashtra", "Thane", ["2002"], "RL-THANE", "2025-06", "THANE METRO", _RL_FRONTS),
    ("anuppur", "Anuppur", "railway", "running", "Madhya Pradesh", "Anuppur", ["1908"], "RL-ANUPP", "2025-04", "Anuppur Thermal Energy - Rail", _RL_FRONTS),
    ("dlf", "DLF", "railway", "running", "Haryana", "Gurugram", ["1153"], "RL-DLF", "2025-08", "DLF Cyber City Gurugram", _RL_FRONTS),
    # BESS, solar, T&D. Banaskantha is the NVVN 185 MW plant (its SPV is named for Banaskantha); Dholera is taken to be the GUVNL Phase-IV plant,
    # the other BESS plant in the export; ERGS-I is the Angul-Sundargarh 765 kV line.
    ("banaskantha", "Banaskantha", "bess", "running", "Gujarat", "Banaskantha", ["2109"], "NE-BANAS", "2025-10", "NVVN1/BESS-01 185 MW", _BS_FRONTS),
    ("dholera", "Dholera", "bess", "running", "Gujarat", "Ahmedabad", ["2110"], "NE-DHOLERA", "2025-10", "GUVNL/BESS/PHASE-IV 250 MW", _BS_FRONTS),
    ("chorniya", "BESS Chorniya", "bess", "new", "Gujarat", "Patan", [], "NE-CHORN", "2026-07", "", _BS_FRONTS),
    ("bikaner", "Bikaner", "solar", "running", "Rajasthan", "Bikaner", ["2104"], "NE-BIKANER", "2025-06", "Solar Bikaner (HGIEL)", _SL_FRONTS),
    ("jodhpur", "Jodhpur", "solar", "running", "Rajasthan", "Jodhpur", ["2108"], "NE-JODHPUR", "2025-07", "Solar Jodhpur (HGIEL)", _SL_FRONTS),
    ("angul", "TBCB Angul", "td", "running", "Odisha", "Angul", ["2501"], "TD-ANGUL", "2025-12", "TRANSMISSION PROJECT (ERGS-I)", _TD_FRONTS),
    ("upptcl", "UPPTCL Mirzapur-Chunar", "td", "new", "Uttar Pradesh", "Mirzapur", [], "TD-UPPTCL", "2026-06", "", _TD_FRONTS),
    ("jamshedpur", "Jamshedpur 400 kV", "td", "new", "Jharkhand", "East Singhbhum", [], "TD-JSR400", "2026-08", "", _TD_FRONTS),
]
HO_PLANT = ("1001", "HO Jaipur")
VERTICAL_LEAD = {"roads": "Pooja", "railway": "Vikram", "bess": "Meera", "solar": "Meera", "td": "Arjun"}

# ------------------------------------------------------------------------------------------------------------------- materials
# code, description, material group, base unit, alternate unit, alternate units per base unit, planned delivery days, PV index
MATERIALS = [
    ("11000010", "Aggregate 10 mm", "AGGREGATE", "MT", None, None, 3, None),
    ("11000020", "Aggregate 20 mm", "AGGREGATE", "MT", None, None, 3, None),
    ("11000040", "Aggregate 40 mm", "AGGREGATE", "MT", None, None, 3, None),
    ("11000110", "Stone dust", "DUST", "MT", None, None, 3, None),
    ("11000120", "WMM air cooled slag", "WMM", "MT", None, None, 4, None),
    ("11000130", "GSB Grade-I", "GSB", "MT", None, None, 3, None),
    ("11000140", "Boulder", "BOULDER", "MT", None, None, 4, None),
    ("11000150", "Track ballast 65 mm", "BALLAST", "MT", None, None, 5, None),
    ("11000160", "Blanketing material", "BLANKET", "MT", None, None, 4, None),
    ("11000210", "Sand, river (washed)", "SAND", "MT", None, None, 4, None),
    ("11000220", "M-sand (manufactured sand)", "SAND", "MT", None, None, 4, None),
    ("12000010", "Cement OPC 53 grade", "CEMENT", "MT", "BAG", 20, 5, None),
    ("12000020", "Cement PPC", "CEMENT", "MT", "BAG", 20, 5, None),
    ("12000110", "GGBS", "GGBS", "MT", None, None, 7, None),
    ("12000120", "Fly ash", "FLYASH", "MT", None, None, 5, None),
    ("12000130", "Microsilica", "MICROSILICA", "MT", None, None, 10, None),
    ("12000210", "Admixture PCE based", "ADMIXTURE", "KG", None, None, 7, None),
    ("13000008", "TMT bar Fe500D 8 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000010", "TMT bar Fe500D 10 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000012", "TMT bar Fe500D 12 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000016", "TMT bar Fe500D 16 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000020", "TMT bar Fe500D 20 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000025", "TMT bar Fe500D 25 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000032", "TMT bar Fe500D 32 mm", "TMT", "MT", None, None, 7, "STEEL_TMT"),
    ("13000110", "HT strand 12.7 mm", "HTSTRAND", "MT", None, None, 14, None),
    ("13000210", "Structural steel (plates and sections)", "STRUCT", "MT", None, None, 14, "STEEL_STRUCT"),
    ("13000220", "Steel girder fabricated", "STRUCT", "MT", None, None, 45, "STEEL_STRUCT"),
    ("14000010", "Bitumen VG-40", "BITUMEN", "MT", None, None, 10, None),
    ("14000020", "Bitumen VG-30", "BITUMEN", "MT", None, None, 10, None),
    ("14000030", "Bitumen CRMB-55", "BITUMEN", "MT", None, None, 12, None),
    ("14000110", "Bitumen emulsion SS-1", "EMULSION", "MT", None, None, 10, None),
    ("14000120", "Bitumen emulsion RS-1", "EMULSION", "MT", None, None, 10, None),
    ("14000210", "Anti-stripping agent", "EMULSION", "KG", None, None, 10, None),
    ("15000010", "HSD (high speed diesel)", "HSD", "L", None, None, 2, None),
    ("15000020", "LSHS / LDO", "HSD", "L", None, None, 3, None),
    ("15000030", "Thermic oil", "HSD", "L", None, None, 7, None),
    ("21000010", "ERC Mk-V elastic rail clip", "RLY-PWAY", "NO", None, None, 45, None),
    ("21000020", "GRSP (grooved rubber sole plate)", "RLY-PWAY", "NO", None, None, 45, None),
    ("21000030", "GFN liner", "RLY-PWAY", "NO", None, None, 40, None),
    ("21000040", "Rail screw with screw clamp", "RLY-PWAY", "NO", None, None, 30, None),
    ("21000110", "PSC sleeper (BG)", "RLY-PWAY", "NO", None, None, 60, None),
    ("21000210", "OHE mast B-150 (galvanised)", "RLY-OHEMAST", "NO", None, None, 60, "STEEL_STRUCT"),
    ("21000220", "OHE mast B-250 (galvanised)", "RLY-OHEMAST", "NO", None, None, 60, "STEEL_STRUCT"),
    ("21000230", "OHE cantilever assembly", "RLY-OHEMAST", "SET", None, None, 50, None),
    ("21000310", "Catenary wire Cu-Cd 65 sq mm", "RLY-OHEWIRE", "KM", None, None, 75, "LME_CU"),
    ("21000320", "Contact wire 107 sq mm", "RLY-OHEWIRE", "KM", None, None, 75, "LME_CU"),
    ("21000410", "Insulator 9 tonne (25 kV)", "RLY-INSUL", "NO", None, None, 45, None),
    ("21000420", "Isolator 25 kV", "RLY-INSUL", "NO", None, None, 60, None),
    ("21000510", "Signalling cable 6-quad armoured", "RLY-SNT", "KM", None, None, 70, "LME_CU"),
    ("21000520", "Signalling cable 12-core armoured", "RLY-SNT", "KM", None, None, 70, "LME_CU"),
    ("21000610", "Integrated power supply (IPS) system", "RLY-SNT", "SET", None, None, 90, None),
    ("21000620", "Relay, plug-in type", "RLY-SNT", "NO", None, None, 60, None),
    ("21000710", "RCC cable duct", "RLY-SNT", "RM", None, None, 20, None),
    ("21000720", "Terminal block", "RLY-SNT", "NO", None, None, 30, None),
    ("21000810", "Traction transformer 30.24 MVA", "ELE-TFR", "NO", None, None, 270, "IEEMA_TFR"),
    ("31000010", "Power transformer 180 MVA", "ELE-TFR", "NO", None, None, 360, "IEEMA_TFR"),
    ("31000020", "Auto transformer 160 MVA", "ELE-TFR", "NO", None, None, 360, "IEEMA_TFR"),
    ("31000030", "Shunt reactor 80 MVAr", "ELE-TFR", "NO", None, None, 360, "IEEMA_TFR"),
    ("31000040", "Power transformer 40 MVA", "ELE-TFR", "NO", None, None, 240, "IEEMA_TFR"),
    ("31000050", "Inverter duty transformer 12.5 MVA", "ELE-TFR", "NO", None, None, 180, "IEEMA_TFR"),
    ("31000110", "GIS 220 kV (per bay lot)", "ELE-SWG", "LOT", None, None, 365, "IEEMA_SWG"),
    ("31000120", "Circuit breaker 220/145 kV", "ELE-SWG", "LOT", None, None, 450, None),
    ("31000121", "Circuit breaker 400 kV", "ELE-SWG", "LOT", None, None, 365, None),
    ("31000130", "CT and CVT 220/145 kV", "ELE-SWG", "LOT", None, None, 365, None),
    ("31000131", "CT and CVT 400 kV", "ELE-SWG", "LOT", None, None, 270, None),
    ("31000140", "Bus post insulator (BPI)", "ELE-SWG", "LOT", None, None, 365, None),
    ("31000210", "Lattice transmission tower (galvanised)", "TL-TOWER", "MT", None, None, 240, "STEEL_STRUCT"),
    ("31000310", "Conductor ACSR Zebra", "TL-COND", "KM", None, None, 240, "IEEMA_ACSR"),
    ("31000320", "Conductor AL59 Moose", "TL-COND", "KM", None, None, 240, "IEEMA_ACSR"),
    ("31000410", "Insulator string set (composite)", "TL-INSUL", "LOT", None, None, 365, None),
    ("31000510", "Substation extension bay works", "ELE-SWG", "LOT", None, None, 365, None),
    ("31000610", "BESS container 5 MWh", "BESS", "NO", None, None, 150, None),
    ("31000620", "Power conversion system 2.5 MW", "BESS", "NO", None, None, 120, None),
    ("31000630", "33 kV switchgear panel", "ELE-SWG", "NO", None, None, 120, None),
    ("31000640", "Energy management system", "BESS", "SET", None, None, 90, None),
    ("31000710", "Solar string inverter 320 kW", "SOLAR", "NO", None, None, 90, None),
    ("31000720", "Module mounting structure", "SOLAR", "MT", None, None, 60, "STEEL_STRUCT"),
    ("31000730", "Solar O&M spares kit", "SOLAR", "SET", None, None, 30, None),
    ("31000810", "DG set 500 kVA", "DG", "NO", None, None, 60, None),
    ("31000910", "Earthing material", "ELE-MISC", "LOT", None, None, 30, None),
    ("31000920", "Control and relay panel", "ELE-SWG", "SET", None, None, 120, None),
    ("31000930", "FOTE equipment", "ELE-MISC", "LOT", None, None, 90, None),
    ("32000010", "Power cable 33 kV XLPE 3C x 300", "CABLE", "KM", None, None, 60, "LME_AL"),
    ("32000020", "Power cable 1.1 kV 4C x 25", "CABLE", "KM", None, None, 45, "LME_CU"),
    ("32000030", "Control cable 12C x 2.5", "CABLE", "KM", None, None, 45, "LME_CU"),
    ("32000040", "Power cable 220 kV XLPE", "CABLE", "KM", None, None, 180, "LME_AL"),
    ("41000010", "Elastomeric bearing", "BEARING", "CCM", None, None, 30, None),
    ("41000020", "POT-PTFE bearing", "BEARING", "NO", None, None, 45, None),
    ("41000030", "Strip seal expansion joint", "EXPJOINT", "RM", None, None, 45, None),
    ("41000110", "RCC hume pipe NP3 600 mm", "PIPE", "NO", None, None, 15, None),
    ("41000120", "RCC hume pipe NP3 900 mm", "PIPE", "NO", None, None, 15, None),
    ("41000210", "Geotextile non-woven", "GEOSYN", "SQM", None, None, 15, None),
    ("41000220", "Geogrid biaxial", "GEOSYN", "SQM", None, None, 15, None),
    ("41000230", "Geocell", "GEOSYN", "SQM", None, None, 15, None),
    ("41000310", "W-beam crash barrier", "BARRIER", "RM", None, None, 20, None),
    ("41000410", "Drainage spout", "MISC", "NO", None, None, 15, None),
    ("41000510", "Deck sheet (profiled)", "MISC", "SQM", None, None, 20, None),
    ("41000610", "AAC block 200 mm", "MISC", "NO", None, None, 10, None),
    ("41000710", "Shuttering plywood 12 mm", "MISC", "SQM", None, None, 10, None),
    ("41000810", "Crane hire (emergency)", "SERVICE", "DAY", None, None, 1, None),
    ("41000820", "Cable laying and termination (service)", "SERVICE", "KM", None, None, 15, None),
]

# ------------------------------------------------------------------------------------------------------------------- the requirement sheets
# The real Oct-Dec 2026 quantities and rates of the two requirement sheets, for the rows that matter to procurement.
# roads: {sheet row: {project: ([oct, nov, dec], rate)}}
ROADS_SHEET = {
    "Aggregate": {"tumkur": ([51485, 64365, 64024], 650), "jh10": ([56791, 65842, 59582], 950), "jh13": ([32608, 36244, 33703], 730),
                  "jec": ([34856, 33454, 28383], 1100), "tirupati": ([200437, 169528, 231842], 563), "ayodhya": ([28332, 36225, 35072], 1447),
                  "narol": ([42694, 43030, 44294], 973)},
    "Dust": {"tumkur": ([20197, 26424, 25261], 650), "jh13": ([18144, 20358, 20057], 485), "jec": ([11834, 9865, 7952], 700),
             "tirupati": ([46615, 29337, 53111], 563), "ayodhya": ([11555, 16595, 16120], 1447), "narol": ([7419, 7112, 8028], 973)},
    "WMM (Air Cooled Slag)": {"jh10": ([17572, 19151, 13203], 770)},
    "GSB": {"tumkur": ([9505, 9845, 7009], 452), "jh10": ([12925, 43657, 26091], 770), "jh13": ([44269, 70747, 85851], 360),
            "jec": ([28906, 19111, 12538], 453), "tirupati": ([88589, 68970, 75383], 590), "ayodhya": ([35098, 55498, 51752], 1250)},
    "Sand (Wash, Coarse, River, Msand)": {"tumkur": ([7329, 6696, 6718], 839), "jh10": ([13223, 14337, 11736], 889), "jh13": ([8489, 9340, 7883], 895),
                                          "jec": ([3274, 10263, 9489], 1237), "ayodhya": ([7837, 8634, 8858], 1450), "narol": ([16241, 17855, 16316], 973)},
    "Cement": {"tumkur": ([3605, 4186, 3748], 4797), "jh10": ([3096, 3095, 4045], 6571), "jh13": ([2817, 3099, 2616], 4706), "jec": ([3152, 3819, 3571], 6250),
               "tirupati": ([9171, 9373, 10474], 5000), "ayodhya": ([3405, 3611, 3600], 5547), "narol": ([13434, 14507, 13159], 5160)},
    "GGBS": {"tumkur": ([708, 1486, 1430], 3865), "jh10": ([1480, 1454, 1896], 3250), "jh13": ([938, 1033, 872], 2597), "jec": ([1478, 1688, 1541], 2465)},
    "Fly Ash": {"jh10": ([1035, 975, 1267], 615), "jh13": ([915, 1007, 850], 435), "jec": ([731, 1073, 1005], 230), "tirupati": ([1673, 1758, 1758], 945),
                "ayodhya": ([973, 1060, 1083], 1250), "narol": ([5712, 5773, 4754], 1950)},
    "Steel (HYSD)": {"tumkur": ([868, 771, 530], 52000), "jh10": ([633, 1179, 1500], 50318), "jh13": ([1068, 1176, 993], 52038), "jec": ([1462, 1540, 1709], 51200),
                     "tirupati": ([959, 495, 0], 52600), "ayodhya": ([587, 665, 743], 53000), "narol": ([2849, 3110, 2829], 54440)},
    "Bitumen-VG-40": {"tumkur": ([581, 839, 1038], 76884), "jh10": ([499, 1151, 839], 56186), "jh13": ([1574, 1771, 1743], 80181), "jec": ([488, 529, 488], 38244),
                      "tirupati": ([2075, 2241, 2490], 75780), "ayodhya": ([265, 334, 267], 39126), "narol": ([456, 466, 426], 49122)},
    "Bitumen-CRMB": {"tirupati": ([1436, 1550, 1723], 73852)},
    "Emulsion-SS1": {"tumkur": ([62, 64, 55], 109177), "jh10": ([16, 37, 27], 65200), "jh13": ([41, 61, 80], 102486), "jec": ([68, 74, 68], 58298),
                     "tirupati": ([296, 143, 313], 100850), "ayodhya": ([24, 28, 30], 58663)},
    "Emulsion-RS1": {"tumkur": ([40, 37, 20], 57022), "jh13": ([64, 77, 81], 50948), "jec": ([38, 41, 38], 33198), "tirupati": ([136, 99, 163], 56771),
                     "ayodhya": ([8, 10, 8], 27388)},
    "HT Strand": {"jh10": ([20, 25, 25], 62875), "jh13": ([20, 28, 22], 63035), "jec": ([170, 53, 60], 69000), "narol": ([177, 177, 177], 72300)},
    "Admixture": {"jh10": ([34689, 38228, 49235], 74), "jec": ([37921, 46141, 42797], 88), "tirupati": ([37524, 38637, 38637], 51),
                  "ayodhya": ([30656, 32753, 32645], 75), "narol": ([134, 145, 132], 67)},
    "HSD": {"jh10": ([479801, 595082, 391828], 100), "ayodhya": ([399383, 440742, 441793], 90), "narol": ([92544, 91301, 90275], 90)},
    "LSHS/LDO": {"tumkur": ([63665, 80433, 79916], 56), "jh10": ([56086, 129475, 94358], 58), "ayodhya": ([31891, 35279, 44469], 60)},
    "Hume Pipe 600": {"jh10": ([100, 100, 0], 588), "jh13": ([306, 139, 0], 5200), "jec": ([0, 1022, 1022], 6200), "ayodhya": ([102, 115, 109], 6200)},
    "Geogrid": {"jec": ([94517, 62169, 41180], 70)},
    "W Beam Crash Barrier": {"tirupati": ([17000, 15200, 14000], 2000)},
    "Elastomeric Bearing": {"jh10": ([1620000, 1822500, 3442500], 0.82), "jec": ([2939198, 6870460, 16819567], 0.8), "narol": ([2009000, 2009000, 2009000], 1)},
    "POT-PTFE Bearing": {"narol": ([28, 28, 28], 24330)},
    "Steel Girder": {"ayodhya": ([0, 470, 470], 90000)},
    "Deck Sheet": {"jec": ([8500, 9500, 9500], 1025), "narol": ([6266, 5873, 7122], 910)},
    "Drainage Spout": {"jec": ([537, 806, 698], 3000), "narol": ([122, 122, 114], 2460)},
    "Strip Seal Expansion Joint (With Stud & Modular)": {"jec": ([208, 313, 271], 34000)},
}
ROADS_UNITS = {"Aggregate": "MT", "Dust": "MT", "WMM (Air Cooled Slag)": "MT", "GSB": "MT", "Sand (Wash, Coarse, River, Msand)": "MT", "Cement": "MT", "GGBS": "MT",
               "Fly Ash": "MT", "Steel (HYSD)": "MT", "Bitumen-VG-40": "MT", "Bitumen-CRMB": "MT", "Emulsion-SS1": "MT", "Emulsion-RS1": "MT", "HT Strand": "MT",
               "Admixture": "KG", "HSD": "Ltr.", "LSHS/LDO": "Ltr.", "Hume Pipe 600": "No.", "Geogrid": "Sqm.", "W Beam Crash Barrier": "RM",
               "Elastomeric Bearing": "CCM", "POT-PTFE Bearing": "No.", "Steel Girder": "MT", "Deck Sheet": "Sqm.", "Drainage Spout": "No.",
               "Strip Seal Expansion Joint (With Stud & Modular)": "RM"}
ROADS_EXTRA_ROWS = ["Microsilica", "Bag House Filler", "Bitumen-VG-30", "Bitumen-PMB", "Pre-Stressing Material", "Steel Liner", "GFRP", "Steel Fiber",
                    "Structural Steel", "Dowel Bar", "Two-Seal Modular Type Expansion joint", "Anti-Stripping Agent", "Mastic Asphalt", "Hume Pipe 900",
                    "Geotextile", "Geocell", "Thermic Oil", "Royalty ( Aggregate & Soil)", "Other Materials"]
RAILWAY_ORDER = ["rvnl", "kanpur", "dhule", "aurangabad", "gaya", "ndls", "thane", "anuppur", "dlf"]
# railway: {sheet row: {project: ([oct, nov, dec], rate)}}
RAILWAY_SHEET = {
    "Aggregate- 10MM": {"rvnl": ([470, 373, 544], 1075), "kanpur": ([1251, 1260, 1298], 1000), "dhule": ([1855, 1932, 1982], 810), "aurangabad": ([4517, 4849, 3322], 760),
                        "gaya": ([2968, 2517, 3419], 1550), "ndls": ([603, 682, 755], 1154), "thane": ([316, 690, 899], 850), "anuppur": ([233, 669, 493], 500)},
    "Aggregate- 20 MM": {"rvnl": ([574, 454, 663], 1075), "kanpur": ([1541, 1552, 1598], 1280), "dhule": ([0, 0, 2488], 875), "aurangabad": ([5584, 5951, 4116], 790),
                         "gaya": ([4451, 5134, 3768], 1825), "ndls": ([862, 973, 1074], 1248), "thane": ([507, 1103, 1440], 850), "anuppur": ([349, 1004, 736], 500)},
    "Dust": {"dhule": ([5364, 4451, 3451], 950), "anuppur": ([1835, 0, 0], 1040)},
    "GSB/Boulder": {"gaya": ([6630, 7735, 9945], 1340), "anuppur": ([96, 112, 0], 730)},
    "Ballast": {"dhule": ([33495, 39963, 37404], 712), "aurangabad": ([15000, 20000, 20000], 1144), "anuppur": ([0, 0, 13442], 500)},
    "Blanketing Material": {"aurangabad": ([32659, 13854, 18911], 835), "gaya": ([78434, 86190, 89063], 1080), "anuppur": ([20209, 37892, 39155], 500)},
    "Sand (Wash, Coarse, River, Msand)": {"rvnl": ([795, 634, 924], 1200), "kanpur": ([1991, 1944, 2006], 1000), "aurangabad": ([5877, 6092, 4201], 1350),
                                          "gaya": ([5576, 6526, 4626], 745), "ndls": ([975, 1097, 1215], 1185), "thane": ([574, 1247, 1635], 1100),
                                          "anuppur": ([307, 886, 649], 1040)},
    "Cement": {"rvnl": ([396, 322, 471], 5932), "kanpur": ([1070, 1058, 1090], 5084), "dhule": ([819, 854, 875], 5000), "aurangabad": ([2485, 2695, 1952], 5254),
               "gaya": ([2796, 3456, 2136], 6186), "ndls": ([558, 630, 693], 5407), "thane": ([281, 619, 798], 6000), "anuppur": ([175, 512, 364], 5500)},
    "GGBS": {"thane": ([22, 44, 63], 4500)},
    "Fly Ash": {"kanpur": ([183, 184, 190], 1125), "ndls": ([91, 99, 109], 1600)},
    "Steel (HYSD)": {"rvnl": ([221, 175, 191], 56500), "kanpur": ([100, 200, 200], 55000), "dhule": ([326, 339, 201], 55000), "aurangabad": ([695, 736, 513], 55000),
                     "gaya": ([956, 1345, 567], 50000), "ndls": ([195, 230, 241], 55557), "thane": ([117, 249, 306], 54000), "anuppur": ([123, 123, 123], 58000),
                     "dlf": ([262, 298, 328], 61185)},
}
RAILWAY_UNITS = {"Aggregate- 10MM": "MT", "Aggregate- 20 MM": "MT", "Dust": "MT", "GSB/Boulder": "MT", "Ballast": "MT", "Blanketing Material": "MT",
                 "Sand (Wash, Coarse, River, Msand)": "MT", "Cement": "MT", "GGBS": "MT", "Fly Ash": "MT", "Steel (HYSD)": "MT"}
RAILWAY_EXTRA_ROWS = ["Ultrafine Fly Ash", "Bag House Filler", "Bitumen-VG-40", "Bitumen-VG-30", "HT Strand", "Structural Steel", "HSD", "Other Materials"]

# A sheet row -> the material codes it stands for, and the code a PO for it uses (the first). The answer a person gave (answers.yaml repeats it).
SHEET_MATERIALS = {
    "Aggregate": ["11000020", "11000010", "11000040"], "Aggregate- 10MM": ["11000010"], "Aggregate- 20 MM": ["11000020"], "Dust": ["11000110"],
    "WMM (Air Cooled Slag)": ["11000120"], "GSB": ["11000130"], "GSB/Boulder": ["11000130", "11000140"], "Ballast": ["11000150"],
    "Blanketing Material": ["11000160"], "Sand (Wash, Coarse, River, Msand)": ["11000210", "11000220"], "Cement": ["12000010", "12000020"],
    "GGBS": ["12000110"], "Fly Ash": ["12000120"], "Microsilica": ["12000130"], "Admixture": ["12000210"],
    "Steel (HYSD)": ["13000016", "13000012", "13000020", "13000010", "13000025", "13000008", "13000032"], "HT Strand": ["13000110"],
    "Structural Steel": ["13000210"], "Steel Girder": ["13000220"], "Bitumen-VG-40": ["14000010"], "Bitumen-VG-30": ["14000020"],
    "Bitumen-CRMB": ["14000030"], "Emulsion-SS1": ["14000110"], "Emulsion-RS1": ["14000120"], "Anti-Stripping Agent": ["14000210"],
    "HSD": ["15000010"], "LSHS/LDO": ["15000020"], "Thermic Oil": ["15000030"], "Hume Pipe 600": ["41000110"], "Hume Pipe 900": ["41000120"],
    "Geotextile": ["41000210"], "Geogrid": ["41000220"], "Geocell": ["41000230"], "W Beam Crash Barrier": ["41000310"],
    "Elastomeric Bearing": ["41000010"], "POT-PTFE Bearing": ["41000020"], "Strip Seal Expansion Joint (With Stud & Modular)": ["41000030"],
    "Drainage Spout": ["41000410"], "Deck Sheet": ["41000510"],
}

# ------------------------------------------------------------------------------------------------------------------- vendors
# code, name, category, state, city, msme, materials (groups) it supplies, payment-terms key, regions (project ids) it serves
# The renamed vendor appears twice (old code, new code). The look-alike, spot-offer and work-contractor senders are set up in the mail module.
VENDORS = [
    # aggregates and sand, by region
    ("100101", "Damodar Stone Crushers", "aggregates", "Jharkhand", "Ranchi", True, ["AGGREGATE", "DUST", "GSB", "WMM", "BOULDER"], "Z030", ["jh10", "jh13"]),
    ("100102", "Subarnarekha Aggregates", "aggregates", "Jharkhand", "Jamshedpur", True, ["AGGREGATE", "DUST", "GSB", "BOULDER"], "Z030", ["jec", "jh13", "jamshedpur"]),
    ("100103", "Chhotanagpur Minerals and Metals", "aggregates", "Jharkhand", "Khunti", False, ["AGGREGATE", "GSB", "SAND"], "Z045", ["jh10", "jh13"]),
    ("100104", "Tumakuru Stone Industries", "aggregates", "Karnataka", "Tumakuru", True, ["AGGREGATE", "DUST", "GSB"], "Z030", ["tumkur"]),
    ("100105", "Nandi Hills Aggregates", "aggregates", "Karnataka", "Doddaballapur", True, ["AGGREGATE", "DUST", "SAND"], "Z030", ["tumkur"]),
    ("100106", "Sabarmati Aggregates and Metals", "aggregates", "Gujarat", "Ahmedabad", False, ["AGGREGATE", "DUST", "SAND"], "Z045", ["narol", "dholera", "banaskantha"]),
    ("100107", "Kutch Grit Suppliers", "aggregates", "Gujarat", "Bhuj", True, ["AGGREGATE", "DUST", "GSB"], "Z030", ["narol", "chorniya"]),
    ("100108", "Saryu Stone Crusher", "aggregates", "Uttar Pradesh", "Ayodhya", True, ["AGGREGATE", "DUST", "GSB", "SAND"], "Z030", ["ayodhya"]),
    ("100109", "Vindhya Grit and Ballast", "aggregates", "Uttar Pradesh", "Mirzapur", True, ["AGGREGATE", "BALLAST", "GSB"], "Z030", ["gew05", "upptcl", "kanpur"]),
    ("100110", "Ganga Valley Minerals", "aggregates", "Uttar Pradesh", "Unnao", False, ["AGGREGATE", "SAND", "GSB"], "Z045", ["gew05", "kanpur"]),
    ("100111", "Krishna Godavari Stone Works", "aggregates", "Andhra Pradesh", "Vijayawada", True, ["AGGREGATE", "DUST", "GSB"], "Z030", ["ap01", "tirupati"]),
    ("100112", "Khammam Metal Crushers", "aggregates", "Telangana", "Khammam", True, ["AGGREGATE", "DUST", "GSB", "WMM"], "Z030", ["kd01", "kd02"]),
    ("100113", "Tirumala Aggregates", "aggregates", "Andhra Pradesh", "Tirupati", True, ["AGGREGATE", "DUST", "GSB", "SAND"], "Z030", ["tirupati"]),
    ("100114", "Kurukshetra Grit Udyog", "aggregates", "Haryana", "Kurukshetra", True, ["AGGREGATE", "DUST", "GSB"], "Z030", ["karnal", "dlf"]),
    ("100115", "Sone Valley Ballast Suppliers", "aggregates", "Madhya Pradesh", "Shahdol", True, ["AGGREGATE", "BALLAST", "BLANKET", "DUST", "GSB"], "Z030", ["anuppur"]),
    ("100116", "Magadh Stone Works", "aggregates", "Bihar", "Gaya", True, ["AGGREGATE", "BLANKET", "GSB", "BOULDER"], "Z030", ["gaya"]),
    ("100117", "Phalgu Aggregates", "aggregates", "Bihar", "Gaya", True, ["AGGREGATE", "SAND", "BLANKET"], "Z030", ["gaya"]),
    ("100118", "Sahyadri Stone Crushers", "aggregates", "Maharashtra", "Dhule", True, ["AGGREGATE", "DUST", "BALLAST"], "Z030", ["dhule", "aurangabad"]),
    ("100119", "Godavari Ballast Company", "aggregates", "Maharashtra", "Chhatrapati Sambhajinagar", False, ["BALLAST", "BLANKET", "AGGREGATE", "SAND"], "Z045", ["aurangabad", "dhule"]),
    ("100120", "Arpa Minerals", "aggregates", "Chhattisgarh", "Bilaspur", True, ["AGGREGATE", "SAND", "BALLAST"], "Z030", ["rvnl"]),
    ("100121", "Aravali Grit Traders", "aggregates", "Haryana", "Gurugram", True, ["AGGREGATE", "SAND", "DUST"], "Z030", ["ndls", "dlf"]),
    ("100122", "Ulhas Aggregates", "aggregates", "Maharashtra", "Kalyan", True, ["AGGREGATE", "SAND"], "Z030", ["thane", "pune_shirur"]),
    ("100123", "Pandu Nadi Stone Crushers", "aggregates", "Uttar Pradesh", "Kanpur Dehat", True, ["AGGREGATE", "SAND"], "Z030", ["kanpur"]),
    ("100124", "Mahanadi M-Sand", "aggregates", "Odisha", "Angul", True, ["SAND", "AGGREGATE"], "Z030", ["angul"]),
    ("100125", "Pennar Manufactured Sand", "aggregates", "Andhra Pradesh", "Nellore", True, ["SAND"], "Z030", ["tirupati", "ap01"]),
    ("100126", "Bhima Stone Crusher", "aggregates", "Maharashtra", "Shirur", True, ["AGGREGATE", "DUST", "SAND"], "Z030", ["pune_shirur"]),
    ("100127", "Thar Grit Suppliers", "aggregates", "Rajasthan", "Bikaner", True, ["AGGREGATE", "SAND"], "Z030", ["bikaner", "jodhpur"]),
    # cement and binders
    ("100201", "Tarangini Cements Pvt Ltd", "cement", "Andhra Pradesh", "Kurnool", False, ["CEMENT"], "Z045", ["tirupati", "ap01", "kd01", "kd02", "tumkur"]),
    ("100202", "Kailasa Portland Cement Ltd", "cement", "Rajasthan", "Chittorgarh", False, ["CEMENT"], "Z045", ["narol", "karnal", "dlf", "ndls", "dholera", "banaskantha", "chorniya", "bikaner", "jodhpur"]),
    ("100203", "Vasudha Binders LLP", "cement", "Jharkhand", "Bokaro", True, ["GGBS", "FLYASH", "MICROSILICA"], "Z030", ["jh10", "jh13", "jec", "tumkur", "thane", "kanpur", "ndls", "tirupati", "ayodhya", "narol"]),
    ("100204", "Ankur Cement Agencies", "cement", "Uttar Pradesh", "Lucknow", True, ["CEMENT"], "Z030", ["ayodhya", "gew05", "kanpur", "upptcl"]),
    ("100205", "Sri Venkata Cement Traders", "cement", "Jharkhand", "Ranchi", True, ["CEMENT"], "Z030", ["jh10", "jh13", "jec", "jamshedpur"]),
    ("100206", "Rajhans Cement Depot", "cement", "Maharashtra", "Nashik", True, ["CEMENT"], "Z030", ["dhule", "aurangabad", "thane", "pune_shirur"]),
    ("100207", "Purvanchal Cement Traders", "cement", "Bihar", "Patna", True, ["CEMENT"], "Z030", ["gaya", "rvnl", "anuppur", "angul"]),
    # steel
    ("100301", "Narmada Steel and Alloys", "steel", "Gujarat", "Vadodara", False, ["TMT", "STRUCT"], "Z045", ["narol", "dholera", "banaskantha", "chorniya", "pune_shirur", "thane"]),
    ("100302", "Shivam TMT Traders", "steel", "Jharkhand", "Ranchi", True, ["TMT"], "Z030", ["jh10", "jh13", "jec", "tumkur", "tirupati", "ayodhya", "gaya", "rvnl"]),
    ("100303", "Loha Bhandar Steel Agencies", "steel", "Uttar Pradesh", "Kanpur", True, ["TMT"], "Z030", ["kanpur", "ayodhya", "gew05", "karnal", "dlf", "ndls", "upptcl"]),
    ("100304", "Ispat Kendra Traders", "steel", "Maharashtra", "Jalna", True, ["TMT", "STRUCT"], "Z030", ["dhule", "aurangabad", "anuppur", "kd01", "kd02", "ap01"]),
    ("100305", "Raigarh Rolling Mills Ltd", "steel", "Chhattisgarh", "Raigarh", False, ["TMT", "STRUCT", "HTSTRAND"], "ZADV", ["jh10", "jh13", "jec", "narol", "tirupati", "rvnl", "angul", "jamshedpur"]),
    ("100306", "Pratap Prestress Systems", "steel", "Maharashtra", "Pune", True, ["HTSTRAND"], "Z045", ["jh10", "jh13", "jec", "narol"]),
    # bitumen, emulsion, fuel
    ("100401", "Rasayan Bitumen Pvt Ltd", "bitumen", "Gujarat", "Vadodara", False, ["BITUMEN", "EMULSION"], "ZRTG", ["narol", "tumkur", "tirupati", "jh10", "jh13", "jec", "ayodhya"]),
    ("100402", "Highway Emulsions LLP", "bitumen", "Uttar Pradesh", "Mathura", True, ["EMULSION", "BITUMEN"], "Z030", ["ayodhya", "gew05", "karnal", "jh13", "jec"]),
    ("100403", "Tarcoat Bitumen Products", "bitumen", "Andhra Pradesh", "Visakhapatnam", True, ["BITUMEN", "EMULSION"], "ZRTG", ["tirupati", "tumkur", "ap01", "kd01", "kd02"]),
    ("100411", "Ganga Highway Fuels", "fuel", "Uttar Pradesh", "Unnao", True, ["HSD"], "Z015", ["ayodhya", "gew05", "kanpur", "upptcl"]),
    ("100412", "Saurashtra Fuel Point", "fuel", "Gujarat", "Ahmedabad", True, ["HSD"], "Z015", ["narol", "dholera", "banaskantha", "chorniya"]),
    ("100413", "Jharkhand Petro Agencies", "fuel", "Jharkhand", "Ranchi", True, ["HSD"], "Z015", ["jh10", "jh13", "jec", "tumkur", "tirupati"]),
    # bridge and road items
    ("100501", "Elastobond Bearings Pvt Ltd", "bridge items", "Maharashtra", "Pune", True, ["BEARING", "EXPJOINT"], "Z045", ["jh10", "jec", "narol"]),
    ("100502", "Jal Pipes and Precast", "bridge items", "Jharkhand", "Ranchi", True, ["PIPE"], "Z030", ["jh10", "jh13", "jec", "ayodhya"]),
    ("100503", "Unnati Geosynthetics", "bridge items", "Gujarat", "Surat", True, ["GEOSYN"], "Z030", ["jec", "tirupati"]),
    ("100504", "Rakshak Crash Barriers", "bridge items", "Haryana", "Faridabad", True, ["BARRIER"], "Z030", ["tirupati"]),
    ("100505", "Amrit Admixtures LLP", "bridge items", "Gujarat", "Ahmedabad", True, ["ADMIXTURE", "EMULSION"], "Z030", ["jh10", "jec", "tirupati", "ayodhya", "narol"]),
    ("100506", "Formtech Shuttering Systems", "bridge items", "Maharashtra", "Pune", True, ["MISC"], "Z030", ["jec", "narol", "ayodhya", "tumkur", "thane"]),
    # railway: P-Way, OHE, S&T
    ("100601", "Konkan Rail Fittings Pvt Ltd", "railway P-Way", "Maharashtra", "Ratnagiri", True, ["RLY-PWAY"], "Z045", ["dhule", "aurangabad", "kanpur"]),
    ("100231", "Sai Krupa Rail Fittings", "railway P-Way", "Maharashtra", "Nashik", True, ["RLY-PWAY"], "Z045", ["dhule", "aurangabad", "rvnl"]),
    ("100512", "SKR Railtech Pvt Ltd", "railway P-Way", "Maharashtra", "Nashik", True, ["RLY-PWAY"], "Z045", ["dhule", "aurangabad", "rvnl"]),
    ("100603", "Deogiri Rail Components", "railway P-Way", "Maharashtra", "Chhatrapati Sambhajinagar", True, ["RLY-PWAY"], "Z045", ["aurangabad", "dhule"]),
    ("100604", "Bundelkhand Track Products", "railway P-Way", "Uttar Pradesh", "Jhansi", False, ["RLY-PWAY"], "Z045", ["kanpur", "gaya", "rvnl", "anuppur", "dlf"]),
    ("100611", "Uttara OHE Structures Pvt Ltd", "railway OHE", "Uttar Pradesh", "Ghaziabad", False, ["RLY-OHEMAST"], "Z045", ["gaya", "aurangabad", "kanpur", "rvnl"]),
    ("100612", "Trishul Catenary Wires", "railway OHE", "Gujarat", "Halol", False, ["RLY-OHEWIRE"], "ZADV", ["gaya", "aurangabad", "kanpur"]),
    ("100613", "Shakti OHE Fittings", "railway OHE", "Delhi", "New Delhi", True, ["RLY-OHEMAST", "RLY-INSUL"], "Z045", ["gaya", "aurangabad", "ndls", "dlf"]),
    ("100614", "Vidyut Insulators and Fittings", "railway OHE", "West Bengal", "Kolkata", False, ["RLY-INSUL", "TL-INSUL"], "Z045", ["gaya", "aurangabad", "angul"]),
    ("100621", "Sanket Signalling Cables Pvt Ltd", "railway S&T", "Gujarat", "Vadodara", False, ["RLY-SNT", "CABLE"], "Z045", ["kanpur", "aurangabad", "gaya", "rvnl"]),
    ("100622", "Pragati Signal Systems", "railway S&T", "Maharashtra", "Pune", True, ["RLY-SNT"], "Z045", ["aurangabad", "kanpur", "gaya"]),
    ("100623", "Relay and Panel Works", "railway S&T", "Uttar Pradesh", "Noida", True, ["RLY-SNT"], "Z045", ["aurangabad", "kanpur", "ndls"]),
    ("100624", "Ankush Signalling Products", "railway S&T", "Delhi", "New Delhi", True, ["RLY-SNT", "CABLE"], "Z030", ["kanpur", "gaya", "ndls", "dlf"]),
    ("100625", "Kanpur Cable House", "railway S&T", "Uttar Pradesh", "Kanpur", True, ["RLY-SNT", "CABLE"], "ZRTG", ["kanpur"]),
    # electrical equipment, lines, cables
    ("100701", "Kalinga Power Transformers Pvt Ltd", "electrical", "Odisha", "Cuttack", False, ["ELE-TFR"], "ZADV", ["aurangabad", "gaya", "rvnl"]),
    ("100702", "Arya Switchgear and GIS Ltd", "electrical", "Maharashtra", "Nashik", False, ["ELE-SWG"], "ZADV", ["dholera", "banaskantha", "chorniya", "jamshedpur"]),
    ("100703", "Meghdoot Electricals", "electrical", "Gujarat", "Vadodara", False, ["ELE-SWG", "ELE-MISC"], "Z045", ["dholera", "banaskantha", "bikaner", "jodhpur", "angul"]),
    ("100704", "Satpura Reactors and Transformers", "electrical", "Madhya Pradesh", "Bhopal", False, ["ELE-TFR", "ELE-SWG"], "ZADV", ["chorniya", "upptcl", "jamshedpur"]),
    ("100705", "Vardaan Instrument Transformers", "electrical", "Rajasthan", "Jaipur", True, ["ELE-SWG"], "Z045", ["dholera", "banaskantha", "bikaner", "jodhpur"]),
    ("100706", "Ujjwal Transformers Pvt Ltd", "electrical", "Gujarat", "Rajkot", False, ["ELE-TFR"], "ZADV", ["dholera", "banaskantha", "bikaner", "jodhpur"]),
    ("100711", "Mahakal Tower Structures", "lines", "Madhya Pradesh", "Ujjain", False, ["TL-TOWER", "SOLAR"], "ZADV", ["angul", "upptcl", "jamshedpur", "bikaner"]),
    ("100712", "Utkal Conductors Pvt Ltd", "lines", "Odisha", "Bhubaneswar", False, ["TL-COND"], "ZADV", ["angul", "upptcl", "jamshedpur"]),
    ("100713", "Swastik Aluminium Conductors", "lines", "Gujarat", "Silvassa", False, ["TL-COND"], "ZADV", ["angul", "upptcl", "jamshedpur"]),
    ("100714", "Neelachal Insulators", "lines", "Odisha", "Rourkela", True, ["TL-INSUL"], "Z045", ["angul", "upptcl"]),
    ("100721", "Anant Power Cables Pvt Ltd", "cables", "Gujarat", "Vadodara", False, ["CABLE"], "ZLC", ["dholera", "banaskantha", "bikaner", "jodhpur", "chorniya"]),
    ("100722", "Vasant Cables and Conductors", "cables", "Maharashtra", "Nagpur", False, ["CABLE"], "Z045", ["dholera", "banaskantha", "bikaner", "jodhpur", "angul"]),
    ("100723", "Kaveri Control Cables", "cables", "Karnataka", "Bengaluru", True, ["CABLE"], "Z045", ["bikaner", "jodhpur", "dholera", "kanpur"]),
    ("100731", "Huaxin Energy Storage Co., Ltd.", "BESS", "", "Shenzhen", False, ["BESS"], "ZLC", ["dholera", "banaskantha"]),
    ("100732", "Tejas PCS Systems", "BESS", "Gujarat", "Gandhinagar", False, ["BESS"], "ZLC", ["dholera", "banaskantha"]),
    ("100733", "Suryamitra Inverters Pvt Ltd", "solar", "Rajasthan", "Jaipur", False, ["SOLAR"], "Z045", ["bikaner", "jodhpur"]),
    ("100734", "Arka Solar Structures", "solar", "Rajasthan", "Jodhpur", True, ["SOLAR"], "Z030", ["bikaner", "jodhpur"]),
    ("100741", "Pavan Gensets Pvt Ltd", "DG sets", "Uttar Pradesh", "Noida", False, ["DG"], "Z045", ["kanpur", "gaya", "rvnl"]),
    ("100742", "Sangam Earthing Solutions", "electrical", "Uttar Pradesh", "Prayagraj", True, ["ELE-MISC"], "Z030", ["dholera", "banaskantha", "bikaner", "jodhpur", "kanpur", "gaya", "upptcl"]),
    # services and contractors
    ("100801", "Vighnaharta Electrical Contractors", "work contractor", "Uttar Pradesh", "Kanpur", True, ["SERVICE"], "Z030", ["kanpur"]),
    ("100802", "Prithvi Infra Contractors", "work contractor", "Bihar", "Gaya", True, ["SERVICE"], "Z030", ["gaya"]),
    ("100803", "Om Sai Crane Services", "services", "Gujarat", "Ahmedabad", True, ["SERVICE"], "Z015", ["narol", "dholera", "jh10", "tirupati"]),
    ("100804", "Navrang Transport Company", "services", "Gujarat", "Ahmedabad", True, ["SERVICE"], "Z015", ["narol", "dholera", "banaskantha"]),
]
STATE_GST = {"Jharkhand": "20", "Karnataka": "29", "Gujarat": "24", "Uttar Pradesh": "09", "Andhra Pradesh": "37", "Telangana": "36", "Haryana": "06",
             "Madhya Pradesh": "23", "Bihar": "10", "Maharashtra": "27", "Chhattisgarh": "22", "Delhi": "07", "Odisha": "21", "Rajasthan": "08",
             "West Bengal": "19"}
# Payment terms key -> SAP text (the meaning is answered in answers.yaml)
PAYMENT_TERMS = {"Z015": "Net 15 days", "Z030": "Net 30 days", "Z045": "Net 45 days", "ZADV": "10% advance against ABG, balance before dispatch",
                 "ZLC": "100% by LC at sight", "ZRTG": "100% RTGS before dispatch"}

# Domains and contacts on file: generated from the names (a word of the name, .example).
