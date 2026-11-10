"""The unit cost has to add up, and the story has to be the one the prices support."""

from decimal import Decimal

from skyline.finops import network_crossover_rpd, project, quantities, unit_crossover_rpd
from skyline.platform import assemble
from skyline.walk import iter_resources


def test_quantities_match_the_template() -> None:
    assembly = assemble()
    qty = quantities(assembly)
    endpoints = sum(
        1
        for _, _, resource in iter_resources(assembly)
        if resource["Type"] == "AWS::EC2::VPCEndpoint"
        and resource["Properties"].get("VpcEndpointType") == "Interface"
    )
    assert qty.interface_endpoints == endpoints
    assert qty.interface_endpoints == 18
    assert qty.cmks == 7
    assert qty.tgw_attachments == 4
    assert qty.guardrails == 1
    assert qty.load_balancers == 1
    assert qty.task_vcpus == Decimal("1.5")


def test_lines_sum_to_the_total() -> None:
    view = project(assemble(), 100_000)
    sky = sum((Decimal(line["skyline_usd"]) for line in view["lines"]), start=Decimal(0))
    naive = sum((Decimal(line["naive_usd"]) for line in view["lines"]), start=Decimal(0))
    assert sky == Decimal(view["skyline_total"])
    assert naive == Decimal(view["naive_total"])
    assert Decimal(view["model_savings_per_1k"]) > Decimal("5")
    assert Decimal(view["guardrail_full_prompt_per_1k"]) > Decimal(view["guardrail_per_1k"]) * 3


def test_volume_changes_who_is_cheaper() -> None:
    low = project(assemble(), 1_000)
    high = project(assemble(), 100_000)
    assert Decimal(low["skyline_total"]) > Decimal(low["naive_total"])
    assert Decimal(high["skyline_total"]) < Decimal(high["naive_total"])
    crossover = high["crossover_rpd"]
    assert crossover is not None
    assert 1_000 < crossover < 100_000


def test_endpoint_premium_is_not_paid_back_by_bytes() -> None:
    view = project(assemble(), 100_000)
    assert Decimal(view["endpoint_daily"]) > Decimal(view["nat_daily"])
    assert view["endpoint_vs_nat_rpd"] is None or view["endpoint_vs_nat_rpd"] > 1_000_000


def test_crossover_math() -> None:
    assert unit_crossover_rpd(Decimal("1"), Decimal("3"), Decimal("10"), Decimal("1")) == 4500
    assert network_crossover_rpd(Decimal("10"), Decimal("1"), Decimal("0"), Decimal("0")) is None
    assert network_crossover_rpd(Decimal("1"), Decimal("10"), Decimal("0"), Decimal("1")) == 0
