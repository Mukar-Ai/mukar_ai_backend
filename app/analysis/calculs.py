"""
Calcule les indicateurs financiers et de risque à partir du JSON d'extraction
d'un dossier de demande de crédit (voir schema.json du projet).

Chaque indicateur est retourné avec un `label` et une `description` en
français, pensés pour être injectés tels quels dans le prompt envoyé à
Gemini: le modèle doit comprendre à quoi sert chaque chiffre, pas seulement
sa valeur brute.

Usage:
    from credit_calculations import compute_analysis
    result = compute_analysis(extraction_json)  # dict Python
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any


# ======================================================================
# Utilitaires d'extraction sûrs
# ======================================================================

@dataclass
class Metric:
    key: str
    label: str
    description: str
    value: float | int | str | None
    unit: str | None = None
    note: str | None = None  # explique pourquoi la valeur est absente, le cas échéant

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "value": self.value,
            "unit": self.unit,
            "note": self.note,
        }


def _get(data: Any, *path: str, default: Any = None) -> Any:
    """Accès sûr à une valeur imbriquée dans un dict. Retourne `default` si absente."""
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _value(field_obj: Any) -> Any:
    """
    Extrait la valeur d'un champ du schéma. Gère les deux formes possibles
    renvoyées par l'extraction Gemini:
      - objet complet: {"value": X, "source": {...}, "confidence": ..., "status": ...}
      - valeur manquante réduite à: null
    """
    if field_obj is None:
        return None
    if isinstance(field_obj, dict):
        return field_obj.get("value")
    return field_obj


def _round(x: float | None, ndigits: int = 2) -> float | None:
    return round(x, ndigits) if x is not None else None


def _mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _sum_or_none(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) if clean else None


# ======================================================================
# Séries de périodes financières
# ======================================================================

_PERIOD_NUMERIC_FIELDS = [
    "revenue_ht", "revenue_ttc", "purchases", "cost_of_goods_sold",
    "gross_margin", "operating_expenses", "ebe", "depreciation",
    "financial_expenses", "taxes", "net_income",
]


def _extract_period_series(data: dict) -> list[dict[str, Any]]:
    """Retourne les périodes de financial_statements triées, valeurs dépliées."""
    periods_raw = _get(data, "financial_statements", "periods", default=[]) or []
    series = []
    for p in periods_raw:
        entry: dict[str, Any] = {"period": p.get("period")}
        for f in _PERIOD_NUMERIC_FIELDS:
            entry[f] = _value(p.get(f))
        series.append(entry)
    series.sort(key=lambda e: e["period"] or "")
    return series


# ======================================================================
# Indicateurs: activité / revenu
# ======================================================================

def _revenue_metrics(series: list[dict]) -> tuple[list[Metric], dict[str, Any]]:
    metrics = []
    raw: dict[str, Any] = {}

    revenue_points = [(e["period"], e["revenue_ht"]) for e in series if e["revenue_ht"] is not None]
    avg_revenue = _mean([v for _, v in revenue_points])
    raw["average_monthly_revenue"] = avg_revenue

    metrics.append(Metric(
        key="average_monthly_revenue_ht",
        label="Chiffre d'affaires mensuel moyen (HT)",
        description=(
            "Moyenne du chiffre d'affaires hors taxes sur les périodes "
            "pour lesquelles une valeur a été extraite. Reflète le niveau "
            "d'activité récurrent de l'entreprise."
        ),
        value=_round(avg_revenue),
        unit="XAF",
        note=None if revenue_points else "Aucune donnée de chiffre d'affaires disponible.",
    ))

    if len(revenue_points) >= 2:
        first_period, first_val = revenue_points[0]
        last_period, last_val = revenue_points[-1]
        growth = (last_val - first_val) / first_val if first_val else None
        metrics.append(Metric(
            key="revenue_growth_rate",
            label="Évolution du chiffre d'affaires",
            description=(
                f"Variation du chiffre d'affaires entre la première période "
                f"analysée ({first_period}) et la dernière ({last_period}). "
                "Un taux positif indique une activité en croissance sur la "
                "période observée; il ne s'agit pas d'un taux annualisé."
            ),
            value=_round(growth * 100, 1) if growth is not None else None,
            unit="%",
            note=None if growth is not None else "Chiffre d'affaires de la première période nul.",
        ))
    else:
        metrics.append(Metric(
            key="revenue_growth_rate",
            label="Évolution du chiffre d'affaires",
            description="Variation du chiffre d'affaires entre deux périodes.",
            value=None,
            unit="%",
            note="Au moins deux périodes avec chiffre d'affaires sont nécessaires pour ce calcul.",
        ))

    metrics.append(Metric(
        key="number_of_periods_with_revenue",
        label="Nombre de périodes avec chiffre d'affaires connu",
        description="Nombre de mois pour lesquels un chiffre d'affaires a pu être extrait des documents.",
        value=len(revenue_points),
        unit="mois",
    ))

    return metrics, raw


# ======================================================================
# Indicateurs: rentabilité / capacité de remboursement
# ======================================================================

def _profitability_metrics(series: list[dict]) -> tuple[list[Metric], dict[str, Any]]:
    metrics = []
    raw: dict[str, Any] = {}

    expense_points = [e["operating_expenses"] for e in series if e["operating_expenses"] is not None]
    avg_expenses = _mean(expense_points)
    raw["average_operating_expenses"] = avg_expenses

    metrics.append(Metric(
        key="average_monthly_operating_expenses",
        label="Charges d'exploitation mensuelles moyennes",
        description="Moyenne des charges d'exploitation déclarées sur les périodes disponibles.",
        value=_round(avg_expenses),
        unit="XAF",
        note=None if expense_points else "Aucune donnée de charges disponible.",
    ))

    # Marge estimée = revenu - charges, uniquement pour les périodes où les
    # DEUX valeurs sont connues (sinon le calcul serait faussé).
    margins = []
    for e in series:
        if e["revenue_ht"] is not None and e["operating_expenses"] is not None:
            margins.append(e["revenue_ht"] - e["operating_expenses"])
    avg_margin = _mean(margins)
    raw["average_operating_margin"] = avg_margin

    metrics.append(Metric(
        key="average_estimated_monthly_margin",
        label="Marge d'exploitation mensuelle moyenne estimée",
        description=(
            "Estimation simplifiée = chiffre d'affaires HT - charges "
            "d'exploitation, moyennée sur les mois où les deux valeurs sont "
            "connues. C'est une approximation de la capacité de "
            "remboursement de l'entreprise: elle n'intègre pas les impôts, "
            "amortissements, charges financières ni prélèvements du "
            "dirigeant, faute de données disponibles ici."
        ),
        value=_round(avg_margin),
        unit="XAF",
        note=None if margins else "Aucun mois avec revenu ET charges connus simultanément.",
    ))

    return metrics, raw


# ======================================================================
# Indicateurs: demande de crédit
# ======================================================================

def _amortized_monthly_payment(principal: float, annual_rate_percent: float | None, n_months: int) -> tuple[float, str]:
    """
    Mensualité d'un prêt amortissable.
    - Si un taux annuel est fourni: mensualité constante classique
      (taux mensuel = taux annuel / 12).
    - Sinon: remboursement linéaire du capital (principal / durée), une
      approximation qui SOUS-ESTIME la vraie mensualité puisqu'elle ignore
      les intérêts.
    """
    if annual_rate_percent and annual_rate_percent > 0:
        r = (annual_rate_percent / 100) / 12
        payment = principal * r / (1 - (1 + r) ** (-n_months))
        method = (
            "Mensualité constante (formule d'amortissement classique), "
            "taux mensuel dérivé du taux annuel déclaré."
        )
    else:
        payment = principal / n_months
        method = (
            "Estimation simplifiée SANS intérêt (capital / durée) car le "
            "taux d'intérêt souhaité n'est pas renseigné: la vraie "
            "mensualité sera plus élevée si un taux s'applique."
        )
    return payment, method


def _credit_request_metrics(data: dict, revenue_raw: dict) -> tuple[list[Metric], dict[str, Any]]:
    metrics = []
    raw: dict[str, Any] = {}

    requested_amount = _value(_get(data, "credit_request", "requested_amount"))
    term_months = _value(_get(data, "credit_request", "requested_term_months"))
    interest_rate = _value(_get(data, "credit_request", "requested_interest_rate"))
    borrower_contribution = _value(_get(data, "credit_request", "borrower_contribution"))

    raw["requested_amount"] = requested_amount

    if requested_amount is not None and term_months:
        payment, method = _amortized_monthly_payment(requested_amount, interest_rate, term_months)
        raw["estimated_new_loan_installment"] = payment
        metrics.append(Metric(
            key="estimated_new_loan_monthly_installment",
            label="Mensualité estimée du crédit demandé",
            description=f"Mensualité estimée pour le crédit demandé. {method}",
            value=_round(payment),
            unit="XAF/mois",
        ))
    else:
        raw["estimated_new_loan_installment"] = None
        metrics.append(Metric(
            key="estimated_new_loan_monthly_installment",
            label="Mensualité estimée du crédit demandé",
            description="Mensualité estimée pour le crédit demandé.",
            value=None,
            unit="XAF/mois",
            note="Durée du crédit demandé (requested_term_months) non renseignée: mensualité non calculable.",
        ))

    avg_revenue = revenue_raw.get("average_monthly_revenue")
    if requested_amount is not None and avg_revenue:
        ratio = requested_amount / avg_revenue
        metrics.append(Metric(
            key="loan_to_average_monthly_revenue",
            label="Montant demandé / chiffre d'affaires mensuel moyen",
            description=(
                "Nombre de mois de chiffre d'affaires moyen que représente "
                "le montant du crédit demandé. Un ratio élevé signale un "
                "montant important par rapport à l'activité actuelle de "
                "l'entreprise."
            ),
            value=_round(ratio, 2),
            unit="mois de CA",
        ))
    else:
        metrics.append(Metric(
            key="loan_to_average_monthly_revenue",
            label="Montant demandé / chiffre d'affaires mensuel moyen",
            description="Nombre de mois de chiffre d'affaires que représente le montant du crédit demandé.",
            value=None,
            unit="mois de CA",
            note="Montant demandé ou chiffre d'affaires moyen manquant.",
        ))

    if borrower_contribution is not None and requested_amount is not None:
        total_project = borrower_contribution + requested_amount
        ratio = borrower_contribution / total_project if total_project else None
        metrics.append(Metric(
            key="borrower_contribution_ratio",
            label="Part de l'apport personnel dans le financement total",
            description=(
                "Apport personnel du demandeur rapporté au coût total du "
                "projet (apport + crédit demandé). Un apport plus élevé "
                "réduit généralement le risque pour le prêteur."
            ),
            value=_round(ratio * 100, 1) if ratio is not None else None,
            unit="%",
        ))
    else:
        metrics.append(Metric(
            key="borrower_contribution_ratio",
            label="Part de l'apport personnel dans le financement total",
            description="Apport personnel rapporté au coût total du projet.",
            value=None,
            unit="%",
            note="Apport personnel (borrower_contribution) non renseigné.",
        ))

    return metrics, raw


# ======================================================================
# Indicateurs: bilan
# ======================================================================

_BALANCE_SHEET_FIELDS = [
    "total_assets", "fixed_assets", "inventory", "trade_receivables", "cash",
    "equity", "long_term_debt", "short_term_financial_debt", "trade_payables",
    "tax_payables", "other_current_liabilities",
]


def _balance_sheet_metrics(data: dict) -> list[Metric]:
    bs = {f: _value(_get(data, "balance_sheet", f)) for f in _BALANCE_SHEET_FIELDS}
    any_present = any(v is not None for v in bs.values())
    note_missing = None if any_present else "Aucune donnée de bilan disponible dans les documents fournis."

    metrics = []

    working_capital = None
    if all(bs[f] is not None for f in ("inventory", "trade_receivables", "cash", "trade_payables",
                                        "tax_payables", "other_current_liabilities", "short_term_financial_debt")):
        current_assets = bs["inventory"] + bs["trade_receivables"] + bs["cash"]
        current_liabilities = (bs["trade_payables"] + bs["tax_payables"]
                                + bs["other_current_liabilities"] + bs["short_term_financial_debt"])
        working_capital = current_assets - current_liabilities

    metrics.append(Metric(
        key="working_capital",
        label="Fonds de roulement (approché)",
        description=(
            "Actifs courants (stock + créances clients + trésorerie) moins "
            "passifs courants (dettes fournisseurs + dettes fiscales + "
            "autres dettes courantes + dettes financières court terme). "
            "Un fonds de roulement négatif peut indiquer une tension de "
            "trésorerie à court terme."
        ),
        value=_round(working_capital),
        unit="XAF",
        note=note_missing or (None if working_capital is not None else "Données de bilan incomplètes pour ce calcul."),
    ))

    debt_to_equity = None
    if bs["equity"] not in (None, 0) and bs["long_term_debt"] is not None and bs["short_term_financial_debt"] is not None:
        debt_to_equity = (bs["long_term_debt"] + bs["short_term_financial_debt"]) / bs["equity"]

    metrics.append(Metric(
        key="debt_to_equity",
        label="Ratio d'endettement (dettes financières / capitaux propres)",
        description=(
            "Somme des dettes financières long terme et court terme "
            "rapportée aux capitaux propres. Un ratio élevé indique un "
            "endettement important par rapport aux fonds propres de "
            "l'entreprise."
        ),
        value=_round(debt_to_equity, 2),
        note=note_missing or (None if debt_to_equity is not None else "Capitaux propres ou dettes financières manquants/nuls."),
    ))

    return metrics


# ======================================================================
# Indicateurs: dettes existantes
# ======================================================================

def _existing_debt_metrics(data: dict) -> tuple[list[Metric], dict[str, Any]]:
    debts = _get(data, "existing_debts", default=[]) or []
    raw: dict[str, Any] = {}

    outstanding = _sum_or_none([_value(d.get("outstanding_principal")) for d in debts])
    installments = _sum_or_none([_value(d.get("installment_amount")) for d in debts])
    raw["total_existing_installments"] = installments or 0

    metrics = [
        Metric(
            key="number_of_existing_debts",
            label="Nombre de dettes existantes déclarées",
            description="Nombre de crédits ou dettes en cours identifiés dans les documents.",
            value=len(debts),
            note="Aucune dette existante déclarée." if not debts else None,
        ),
        Metric(
            key="total_existing_outstanding_principal",
            label="Capital restant dû total (dettes existantes)",
            description="Somme du capital restant dû sur l'ensemble des dettes existantes identifiées.",
            value=_round(outstanding) if outstanding is not None else (0 if debts else None),
            unit="XAF",
        ),
        Metric(
            key="total_existing_monthly_installments",
            label="Total des mensualités des dettes existantes",
            description=(
                "Somme des mensualités actuellement dues sur les dettes "
                "existantes. Sert de base au calcul de la capacité de "
                "remboursement globale une fois le nouveau crédit ajouté."
            ),
            value=_round(installments) if installments is not None else (0 if debts else None),
            unit="XAF/mois",
        ),
    ]
    return metrics, raw


# ======================================================================
# Indicateurs: capacité de remboursement globale (DSCR)
# ======================================================================

def _debt_service_metrics(profitability_raw: dict, credit_raw: dict, debt_raw: dict) -> list[Metric]:
    monthly_capacity = profitability_raw.get("average_operating_margin")
    new_installment = credit_raw.get("estimated_new_loan_installment")
    existing_installments = debt_raw.get("total_existing_installments", 0)

    if monthly_capacity is None:
        return [Metric(
            key="debt_service_coverage_ratio",
            label="Ratio de couverture du service de la dette (DSCR)",
            description=(
                "Marge d'exploitation mensuelle moyenne divisée par le "
                "total des mensualités (dettes existantes + crédit "
                "demandé). Un ratio supérieur à 1 signifie que l'activité "
                "génère plus que ce qu'il faut pour rembourser ses dettes."
            ),
            value=None,
            note="Marge d'exploitation mensuelle non calculable (revenu ou charges manquants).",
        )]

    total_debt_service = existing_installments + (new_installment or 0)
    if total_debt_service <= 0:
        return [Metric(
            key="debt_service_coverage_ratio",
            label="Ratio de couverture du service de la dette (DSCR)",
            description=(
                "Marge d'exploitation mensuelle moyenne divisée par le "
                "total des mensualités (dettes existantes + crédit "
                "demandé)."
            ),
            value=None,
            note="Aucune mensualité (existante ou demandée) à comparer à la capacité de remboursement.",
        )]

    dscr = monthly_capacity / total_debt_service
    note = None if new_installment is not None else (
        "Mensualité du crédit demandé non incluse (durée du crédit non renseignée); "
        "ce DSCR ne couvre que les dettes existantes."
    )
    return [Metric(
        key="debt_service_coverage_ratio",
        label="Ratio de couverture du service de la dette (DSCR)",
        description=(
            "Marge d'exploitation mensuelle moyenne divisée par le total "
            "des mensualités (dettes existantes + crédit demandé, quand "
            "calculable). Un ratio supérieur à 1 signifie que l'activité "
            "génère plus que ce qu'il faut pour couvrir ses échéances; en "
            "dessous de 1, l'activité seule ne suffit pas à rembourser."
        ),
        value=_round(dscr, 2),
        note=note,
    )]


# ======================================================================
# Indicateurs: informations commerciales (contrats, clients, fournisseurs)
# ======================================================================

def _commercial_metrics(data: dict) -> list[Metric]:
    customers = _get(data, "commercial_information", "customers", default=[]) or []
    suppliers = _get(data, "commercial_information", "suppliers", default=[]) or []
    contracts = _get(data, "commercial_information", "contracts", default=[]) or []

    contract_amounts = [_value(c.get("contract_amount")) for c in contracts]
    contract_amounts = [a for a in contract_amounts if a is not None]
    total_contracted = sum(contract_amounts) if contract_amounts else None

    largest_share = None
    if contract_amounts and total_contracted:
        largest_share = max(contract_amounts) / total_contracted

    metrics = [
        Metric(
            key="number_of_customers",
            label="Nombre de clients identifiés",
            description="Nombre de clients mentionnés dans les documents fournis.",
            value=len(customers),
        ),
        Metric(
            key="number_of_suppliers",
            label="Nombre de fournisseurs identifiés",
            description="Nombre de fournisseurs mentionnés dans les documents fournis.",
            value=len(suppliers),
        ),
        Metric(
            key="number_of_contracts",
            label="Nombre de contrats commerciaux identifiés",
            description="Nombre de contrats commerciaux (clients ou marchés) identifiés dans les documents.",
            value=len(contracts),
        ),
        Metric(
            key="total_contracted_amount",
            label="Montant total des contrats commerciaux",
            description=(
                "Somme des montants de tous les contrats commerciaux "
                "identifiés. Donne une idée du chiffre d'affaires "
                "potentiel déjà engagé contractuellement."
            ),
            value=_round(total_contracted) if total_contracted is not None else None,
            unit="XAF",
            note=None if contracts else "Aucun contrat identifié dans les documents fournis.",
        ),
        Metric(
            key="largest_contract_concentration",
            label="Concentration sur le plus gros contrat",
            description=(
                "Part du plus gros contrat dans le montant total des "
                "contrats identifiés. Une valeur élevée signale une "
                "dépendance forte à un seul client, ce qui est un facteur "
                "de risque si ce client venait à se retirer."
            ),
            value=_round(largest_share * 100, 1) if largest_share is not None else None,
            unit="%",
            note=None if largest_share is not None else "Non calculable (pas de contrat chiffré identifié).",
        ),
    ]
    return metrics


# ======================================================================
# Indicateurs: flux de trésorerie futurs attendus
# ======================================================================

def _future_cashflow_metrics(data: dict) -> list[Metric]:
    flows = _get(data, "future_cash_flows", default=[]) or []
    amounts = [_value(f.get("expected_collection_amount")) for f in flows]
    amounts = [a for a in amounts if a is not None]
    total = sum(amounts) if amounts else None

    return [
        Metric(
            key="number_of_future_cash_flows",
            label="Nombre d'encaissements futurs attendus",
            description="Nombre d'encaissements futurs identifiés (contrats, commandes en cours...).",
            value=len(flows),
        ),
        Metric(
            key="total_expected_future_cash_flows",
            label="Total des encaissements futurs attendus",
            description=(
                "Somme des montants d'encaissements futurs attendus "
                "identifiés dans les documents (issus de contrats, "
                "commandes...). À rapprocher du montant du crédit demandé "
                "pour évaluer la capacité de remboursement future."
            ),
            value=_round(total) if total is not None else None,
            unit="XAF",
            note=None if flows else "Aucun encaissement futur identifié dans les documents fournis.",
        ),
    ]


# ======================================================================
# Indicateurs: bancaires
# ======================================================================

def _banking_metrics(data: dict) -> list[Metric]:
    total_credits = _value(_get(data, "banking", "aggregates", "total_credits"))
    total_debits = _value(_get(data, "banking", "aggregates", "total_debits"))
    average_balance = _value(_get(data, "banking", "aggregates", "average_balance"))

    net_flow = None
    if total_credits is not None and total_debits is not None:
        net_flow = total_credits - total_debits

    overdraft_events = _get(data, "banking", "overdraft_events", default=[]) or []
    rejected_transactions = _get(data, "banking", "rejected_transactions", default=[]) or []
    bank_fees = _get(data, "banking", "bank_fees", default=[]) or []
    accounts = _get(data, "banking", "accounts", default=[]) or []

    bank_fees_total = _sum_or_none([f.get("amount") for f in bank_fees])
    has_any_banking_data = bool(accounts) or total_credits is not None or total_debits is not None

    note_no_data = None if has_any_banking_data else "Aucun relevé bancaire fourni ou analysé."

    return [
        Metric(
            key="number_of_bank_accounts",
            label="Nombre de comptes bancaires analysés",
            description="Nombre de comptes bancaires identifiés dans les relevés fournis.",
            value=len(accounts),
            note=note_no_data,
        ),
        Metric(
            key="net_banking_flow",
            label="Flux bancaire net (crédits - débits)",
            description=(
                "Différence entre le total des entrées et le total des "
                "sorties sur la période bancaire analysée."
            ),
            value=_round(net_flow) if net_flow is not None else None,
            unit="XAF",
            note=note_no_data or (None if net_flow is not None else "Totaux de crédits/débits non disponibles."),
        ),
        Metric(
            key="average_account_balance",
            label="Solde bancaire moyen",
            description="Solde moyen observé sur la période bancaire analysée.",
            value=_round(average_balance) if average_balance is not None else None,
            unit="XAF",
            note=note_no_data,
        ),
        Metric(
            key="number_of_overdraft_events",
            label="Nombre de dépassements de découvert",
            description=(
                "Nombre d'incidents de dépassement de découvert autorisé "
                "identifiés. Un indicateur de tension de trésorerie."
            ),
            value=len(overdraft_events),
            note=note_no_data,
        ),
        Metric(
            key="number_of_rejected_transactions",
            label="Nombre de transactions rejetées",
            description=(
                "Nombre de rejets (chèques, prélèvements...) identifiés sur "
                "la période analysée. Un indicateur de risque de paiement."
            ),
            value=len(rejected_transactions),
            note=note_no_data,
        ),
        Metric(
            key="total_bank_fees",
            label="Total des frais bancaires",
            description="Somme des frais bancaires identifiés sur la période analysée.",
            value=_round(bank_fees_total) if bank_fees_total is not None else None,
            unit="XAF",
            note=note_no_data,
        ),
    ]


# ======================================================================
# Indicateurs: qualité et complétude de l'extraction
# ======================================================================

def _data_quality_metrics(data: dict) -> list[Metric]:
    missing = _get(data, "missing_information", default=[]) or []
    required_missing = [m for m in missing if m.get("required") is True]

    meta = _get(data, "extraction_metadata", default={}) or {}

    return [
        Metric(
            key="overall_extraction_confidence",
            label="Confiance globale de l'extraction",
            description=(
                "Score de confiance global calculé par le moteur "
                "d'extraction sur l'ensemble du dossier. Sert à pondérer "
                "la fiabilité des chiffres ci-dessus."
            ),
            value=meta.get("overall_confidence"),
        ),
        Metric(
            key="missing_required_fields_count",
            label="Nombre de champs obligatoires manquants",
            description=(
                "Nombre d'informations jugées obligatoires pour l'analyse "
                "du dossier mais absentes des documents fournis. Une "
                "recommandation ne devrait pas être définitive tant que "
                "ces champs restent manquants."
            ),
            value=len(required_missing),
        ),
        Metric(
            key="missing_fields_total_count",
            label="Nombre total de champs manquants (obligatoires ou non)",
            description="Nombre total d'informations manquantes identifiées, y compris non-obligatoires.",
            value=len(missing),
        ),
    ]


# ======================================================================
# Point d'entrée principal
# ======================================================================

def compute_analysis(data: dict) -> dict[str, Any]:
    """
    Calcule l'ensemble des indicateurs à partir du JSON d'extraction.
    Retourne un dict JSON-sérialisable prêt à être injecté dans un prompt.
    """
    series = _extract_period_series(data)

    metrics: list[Metric] = []

    revenue_metrics, revenue_raw = _revenue_metrics(series)
    metrics += revenue_metrics

    profitability_metrics, profitability_raw = _profitability_metrics(series)
    metrics += profitability_metrics

    credit_metrics, credit_raw = _credit_request_metrics(data, revenue_raw)
    metrics += credit_metrics

    metrics += _balance_sheet_metrics(data)

    debt_metrics, debt_raw = _existing_debt_metrics(data)
    metrics += debt_metrics

    metrics += _debt_service_metrics(profitability_raw, credit_raw, debt_raw)
    metrics += _commercial_metrics(data)
    metrics += _future_cashflow_metrics(data)
    metrics += _banking_metrics(data)
    metrics += _data_quality_metrics(data)

    return {
        "company_name": _value(_get(data, "company", "legal_name")),
        "requested_amount": credit_raw.get("requested_amount"),
        "requested_amount_currency": _get(data, "credit_request", "requested_amount", "currency"),
        "metrics": [m.to_dict() for m in metrics],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python credit_calculations.py chemin/vers/extraction.json", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        extraction_data = json.load(f)

    print(json.dumps(compute_analysis(extraction_data), ensure_ascii=False, indent=2))