"""Conservative, single-turn requirement extraction with exact source offsets.

This does not confirm a requirement card or infer unstated operating limits.
"""

import re
from typing import Any

PRODUCT = re.compile(r"(?<![A-Za-z0-9])(?:MP4570|TPS54331|TPS562201|TPS562208|LT8610)(?![A-Za-z0-9])", re.IGNORECASE)
NUMBER = r"\d+(?:\.\d+)?"
VOLTAGE = rf"({NUMBER})\s*(?:V|伏(?:特)?)(?![A-Za-z])"
CURRENT = rf"({NUMBER})\s*(mA|A|毫安|安培|安)(?![A-Za-z])"


def understand(query: str) -> dict[str, Any]:
    """Return only explicit parameters; every parameter points into *query*.

    Values use V and A for numeric parameters. UNKNOWN and NOT_FORCED_AIR
    are explicit source statements, not assumptions about operating conditions.
    """
    result: dict[str, Any] = {
        "products": list(dict.fromkeys(m.group().upper() for m in PRODUCT.finditer(query))),
        "parameters": [],
        "ambiguities": [],
        "selection": bool(re.search(r"推荐|选(?:个|一|型|择)|recommend|select|choose", query, re.IGNORECASE)),
    }

    def add(field: str, value: Any, unit: str | None, start: int, end: int) -> None:
        result["parameters"].append({
            "field": field, "value": value, "unit": unit,
            "source_text": query[start:end], "start": start, "end": end,
        })

    alternatives = re.search(rf"{VOLTAGE}\s*(?:或(?:者)?|or|/)\s*{VOLTAGE}", query, re.IGNORECASE)
    if alternatives:
        result["ambiguities"].append("输入/输出电压存在多个备选值，请明确：" + alternatives.group())
    else:
        conversion = re.search(rf"{VOLTAGE}\s*(?:转|到|to|->|→)\s*{VOLTAGE}", query, re.IGNORECASE)
        if conversion and re.search(r"(?:不是|并非|不要|not)\s*$", query[:conversion.start()], re.IGNORECASE):
            result["ambiguities"].append("电压转换条件被否定，请给出实际输入和输出电压。")
        elif conversion:
            for field, match in zip(("vin", "vout"), re.finditer(VOLTAGE, conversion.group(), re.IGNORECASE)):
                add(field, float(match.group(1)), "V", conversion.start() + match.start(), conversion.start() + match.end())
        else:
            for field, label in (("vin", r"输入(?:电压)?|input(?:\s+voltage)?|VIN"), ("vout", r"输出(?:电压)?|output(?:\s+voltage)?|VOUT")):
                matches = list(re.finditer(rf"(?:{label})\s*[:=：]?\s*{VOLTAGE}", query, re.IGNORECASE))
                if len(matches) == 1:
                    match = matches[0]
                    if re.search(r"(?:不是|并非|不要|not)\s*$", query[:match.start()], re.IGNORECASE):
                        result["ambiguities"].append(f"{field} 陈述被否定，请明确实际值。")
                        continue
                    add(field, float(match.group(1)), "V", match.start(), match.end())
                elif len(matches) > 1:
                    result["ambiguities"].append(f"{field} 有多个陈述，请明确当前值。")

    correction = re.search(
        rf"(?:不是|并非|not)\s*(?P<old>{NUMBER})\s*(?P<oldunit>mA|A|毫安|安培|安)"
        rf"\s*[,，;；]?\s*(?:而?是|but|rather)\s*(?P<new>{NUMBER})\s*"
        rf"(?P<newunit>mA|A|毫安|安培|安)", query, re.IGNORECASE)
    currents = []
    for match in re.finditer(CURRENT, query, re.IGNORECASE):
        prefix = query[max(0, match.start() - 20):match.start()]
        if re.search(r"(?:不是|并非|不要|not)\s*$", prefix, re.IGNORECASE):
            continue
        currents.append(match)
    # A bare current can mean peak, switch limit, load, etc. Require a label
    # or an explicit correction, rather than inventing continuous current.
    if correction:
        context = query[max(0, correction.start() - 30):correction.start()]
        if not re.search(r"峰值|peak", context, re.IGNORECASE):
            value = float(correction.group("new"))
            if correction.group("newunit").lower() in ("ma", "毫安"):
                value /= 1000
            start = correction.start("new")
            end = correction.end("newunit")
            add("iout_continuous", value, "A", start, end)
        else:
            result["ambiguities"].append("电流已纠正，但未明确它是持续、峰值还是限流条件。")
    elif len(currents) == 1:
        match = currents[0]
        prefix = query[max(0, match.start() - 35):match.start()]
        if re.search(r"(?:(?:持续|连续)(?:输出|电流)?\s*[:：=]?|continuous(?:\s+(?:output|current|of))*\s*[:=]?|不是.*是|not.*(?:but|rather))\s*$", prefix, re.IGNORECASE):
            value = float(match.group(1))
            if match.group(2).lower() in ("ma", "毫安"):
                value /= 1000
            if re.search(r"峰值|peak|限流|current\s+limit", prefix, re.IGNORECASE):
                result["ambiguities"].append("电流修正涉及峰值或限流，请明确电流类别。")
            elif re.search(r"(?:不要|不是|并非|not)\s*(?:持续|连续|continuous)", prefix, re.IGNORECASE):
                result["ambiguities"].append("持续电流条件被否定，请明确实际值。")
            else:
                add("iout_continuous", value, "A", match.start(), match.end())
    elif len(currents) > 1:
        result["ambiguities"].append("多个电流值需要明确持续、峰值或限流条件。")

    for pattern, field, value in (
        (r"(?:不知道(?:有没(?:有)?|是否有)浪涌|浪涌(?:电压)?\s*(?:未知|不明|不知道)|(?:未知|不明)\s*浪涌|surge\s*(?:is\s*)?unknown|unknown\s+surge)", "surge", "UNKNOWN"),
        (r"(?:不要|不允许|不用|不能)\s*(?:强制)?风冷|(?:no|without)\s+forced[ -]air", "cooling_method", "NOT_FORCED_AIR"),
    ):
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            add(field, value, None, match.start(), match.end())
    if not result["products"] and re.search(r"它|上一颗|这两颗|\bit\b|\bthese two\b", query, re.IGNORECASE):
        result["ambiguities"].append("请明确所指芯片型号；本演示不从历史回答继承参数。")
    return result
