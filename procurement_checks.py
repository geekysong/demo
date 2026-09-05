"""Deterministic procurement evidence; no LLM output can authorize payment."""
from datetime import datetime, timezone


def decision_record(selected, considered, request, policy):
    return {
        'mode': 'deterministic_policy',
        'objective': request,
        'selected_id': selected['id'],
        'explanation': f"Selected {selected['name']}: matches the requested category and passes configured policy checks; lowest price among eligible candidates (stable input order breaks ties).",
        'candidates': considered,
        'constraints': dict(policy),
        'limitations': ['Trust scores and endpoint freshness are demo proxies, not verified data quality.',
                        'Delivery must be checked separately; no LLM reasoning is used.'],
    }


def validate_quote(quote, selected, pay_to, policy, spent):
    expected = {'scheme': 'exact', 'network': 'xrpl:1', 'asset': 'XRP', 'payTo': pay_to}
    for key, value in expected.items():
        if quote.get(key) != value:
            raise ValueError(f'Quote rejected: {key} does not match approved payment binding')
    amount = quote.get('amount')
    if not isinstance(amount, str) or not amount.isascii() or not amount.isdigit() or int(amount) <= 0:
        raise ValueError('Quote rejected: amount must be positive integer drops')
    amount = int(amount)
    if amount != selected['price_drops']:
        raise ValueError('Quote rejected: price changed after selection')
    if amount > policy.get('per_tx_cap_drops', amount):
        raise ValueError('Quote rejected: per-transaction budget exceeded')
    if spent + amount > policy.get('per_applicant_cumulative_cap_drops', spent + amount):
        raise ValueError('Quote rejected: cumulative budget exceeded')
    return {'status': 'pass', 'amount_drops': amount, 'network': 'xrpl:1', 'pay_to': pay_to}


def confirm_payment(result, account, destination, amount):
    tx = result.get('tx_json', result)
    meta = result.get('meta', {})
    return bool(result.get('validated') is True and isinstance(meta, dict)
                and meta.get('TransactionResult') == 'tesSUCCESS'
                and tx.get('TransactionType') == 'Payment'
                and tx.get('Account') == account and tx.get('Destination') == destination
                and tx.get('Amount') == str(amount)
                and meta.get('delivered_amount') == str(amount)
                and not (int(tx.get('Flags', 0)) & 0x20000))


def validate_delivery(payload, data_type, region, freshness_days, now=None):
    """A sample may be received successfully, but never certifies an applicant."""
    now = now or datetime.now(timezone.utc)
    checks = []
    def add(name, status, evidence):
        checks.append({'name': name, 'status': status, 'evidence': evidence})
    if not isinstance(payload, dict) or not isinstance(payload.get('result'), dict):
        return {'status': 'rejected', 'checks': [{'name': 'schema', 'status': 'fail', 'evidence': 'Missing object result'}]}
    result = payload['result']
    add('category', 'pass' if payload.get('data_type') == data_type else 'fail', str(payload.get('data_type')))
    fields = {'business_registration_status': ['lei', 'legal_name', 'entity_status', 'registration_status'],
              'industry_income_benchmarks': ['industry', 'geography', 'period', 'mean_annual_wage']}.get(data_type)
    missing = [key for key in (fields or []) if result.get(key) in (None, '')]
    add('fields', 'unknown' if fields is None else ('fail' if missing else 'pass'),
        'Unsupported data contract' if fields is None else ('Missing: ' + ', '.join(missing) if missing else 'Required fields present'))
    sample = bool(result.get('sample') or 'sample' in str(payload.get('delivery_mode', '')).lower())
    add('provenance', 'unknown', 'Demonstration sample; applicant/source not verified' if sample else 'Source authenticity has not been independently verified')
    actual_region = result.get('jurisdiction') or result.get('geography')
    normalized = str(actual_region or '').upper().replace(' NATIONAL', '')
    requested = str(region or '').upper()
    match = normalized == requested or (len(requested) == 2 and normalized.startswith(requested + '-'))
    add('region', 'unknown' if not requested or not normalized else ('pass' if match else 'fail'),
        f'Requested {region}; received {actual_region}')
    observed = result.get('observed_at') or result.get('as_of')
    if not observed and result.get('period'):
        try:
            # Month-only samples: use month end to avoid declaring them stale too early.
            import calendar
            month = datetime.strptime(result['period'], '%B %Y').replace(tzinfo=timezone.utc)
            observed = month.replace(day=calendar.monthrange(month.year, month.month)[1]).isoformat()
        except (ValueError, TypeError):
            pass
    try:
        observed_time = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        if observed_time.tzinfo is None:
            raise ValueError('Timestamp requires timezone')
        age = (now - observed_time).total_seconds() / 86400
        if freshness_days is None:
            raise ValueError('No freshness requirement')
        add('freshness', 'pass' if 0 <= age <= freshness_days else 'fail',
            f'Observed {observed}; maximum age {freshness_days} days')
    except (AttributeError, ValueError, TypeError):
        add('freshness', 'unknown', 'No verifiable observation timestamp / freshness requirement')
    status = 'rejected' if any(c['status'] == 'fail' for c in checks) else 'unknown' if any(c['status'] == 'unknown' for c in checks) else 'accepted'
    return {'status': status, 'checks': checks}
