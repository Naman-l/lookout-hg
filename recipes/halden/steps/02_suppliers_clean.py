"""Clean the supplier master's free text: country, payment terms, Incoterms, tier, dates.

Defect: the same fact typed many ways by different people (United States / USA / US; NET60 / Net 60 / Net 45 days;
FOB SZ / FOB Shenzhen); a blank tier on 4 records.
Rule: country -> ISO alpha-2, terms -> "Net N" with net days and prepayment share, Incoterm -> term + place.
The raw text stays beside each cleaned field. A blank stays blank (unknown), never a default.
Consequence if ignored: filters and totals by country or terms silently split; a deposit term reads as Net 30.
"""
import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import iso_country, parse_payment_terms, split_incoterm


def run(ctx):
    raw = ctx.t["raw_suppliers"]
    df = pd.DataFrame({"src_row": raw.src_row})
    df["record_id"] = raw.supplier_id.str.strip()
    df["system"] = df.record_id.map(lambda r: "legacy" if r.startswith("V") else "new")
    df["name"] = raw.name
    df["country_raw"] = raw.country
    df["country"] = raw.country.map(iso_country)
    df["city"] = raw.city.replace("", None)
    df["tier"] = pd.to_numeric(raw.tier.replace("", None)).astype("Int64")
    pt = raw.payment_terms.map(parse_payment_terms)
    df["payment_terms_raw"] = raw.payment_terms
    df["payment_terms"] = pt.map(lambda d: d["label"])
    df["net_days"] = pt.map(lambda d: d["net_days"]).astype("Int64")
    df["prepay_pct"] = pt.map(lambda d: d["prepay_pct"]).astype("Int64")
    df["currency"] = raw.currency.replace("", None)
    df["incoterms_raw"] = raw.incoterms
    it = raw.incoterms.map(split_incoterm)
    df["incoterm"] = it.map(lambda x: x[0])
    df["incoterm_place"] = it.map(lambda x: x[1])
    df["contact_name"] = raw.contact_name.replace("", None)
    df["contact_email"] = raw.contact_email.replace("", None)
    df["email_domain"] = raw.contact_email.str.split("@").str[1].str.lower()
    df["status"] = raw.status
    df["created_date"] = raw.created_date
    ctx.t["supplier_records"] = df

    changed = df[df.country_raw != df.country]
    ctx.issue("suppliers.country_spellings", "suppliers.csv",
              "Country typed several ways (United States, USA, US; China, PRC, CN; Taiwan, ROC)",
              len(changed), "fix", "Map every spelling to ISO alpha-2; the raw text is kept in country_raw.",
              "Counting suppliers by country, or matching a supplier's country to a part's origin, would split one country into several.",
              examples(changed.country_raw + " -> " + changed.country), "ERP admin")
    odd = df[df.payment_terms_raw != df.payment_terms]
    ctx.issue("suppliers.payment_terms_spellings", "suppliers.csv",
              "Payment terms typed several ways (NET60, Net 45 days, NET 30)",
              len(odd[odd.net_days.notna()]), "fix", "Parse to net days and a canonical 'Net N' label; the raw text is kept.",
              "Cash-flow views and 'which suppliers are on Net 60' would miss records spelled differently.",
              examples(odd[odd.net_days.notna()].payment_terms_raw + " -> " + odd[odd.net_days.notna()].payment_terms), "ERP admin")
    pre = df[df.prepay_pct.fillna(0) > 0]
    ctx.issue("suppliers.prepayment_terms", "suppliers.csv",
              "Suppliers that want money before shipment (cash in advance, deposit, T/T)",
              len(pre), "flag", "Keep the term as written, set prepay_pct, and show it on the supplier.",
              "Cash leaves before goods arrive; this is the pattern the fraudulent remittance email of 2026-09-23 uses.",
              examples(pre.name + ": " + pre.payment_terms_raw), "@suppliers:" + ",".join(pre.record_id))
    no_tier = df[df.tier.isna()]
    ctx.issue("suppliers.tier_blank", "suppliers.csv", "Supplier tier is blank", len(no_tier), "leave",
              "Leave the tier unknown; do not default it. It shows as 'unknown · ask the buyer'.",
              "A ranking by tier would silently treat these as least important.",
              examples(no_tier.name), "@suppliers:" + ",".join(no_tier.record_id))
