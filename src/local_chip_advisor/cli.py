"""Command-line presentation helpers."""

import argparse

from local_chip_advisor.advisor import LocalChipAdvisor
from local_chip_advisor.ollama_requirements import OllamaRequirementParser
from local_chip_advisor.ranking import (
    RankingCriterion,
    RankingPolicy,
)
from local_chip_advisor.requirements import RequirementReview


def format_requirement_review(
    *,
    review: RequirementReview,
    questions: tuple[str, ...],
) -> str:
    """Format a requirement review for terminal display."""

    lines = [
        f"missing_fields: {review.missing_fields}",
        f"ready_for_confirmation: {review.ready_for_confirmation}",
    ]

    if questions:
        lines.append("questions:")
        lines.extend(
            f"- {question}"
            for question in questions
        )

    return "\n".join(lines)


def format_recommendation_result(result) -> str:
    """Format recommendation buckets and candidate issues for terminal display."""

    lines: list[str] = []

    for bucket_name in (
        "formal",
        "near_match",
        "needs_verification",
    ):
        candidates = getattr(result, bucket_name)

        if not candidates:
            lines.append(f"{bucket_name}: none")
            continue

        lines.append(f"{bucket_name}:")

        for candidate in candidates:
            lines.append(f"- {candidate.product_id}")

            for issue in candidate.issues:
                lines.append(
                    "  "
                    f"{issue.rule_id} | "
                    f"{issue.state} | "
                    f"{issue.requirement} | "
                    f"{issue.reason}"
                )

    return "\n".join(lines)


def run_cli_session(
    *,
    advisor,
    database_path,
    knowledge_base_version: str,
    policy,
    input_fn=input,
    output_fn=print,
):
    """Run one command-line advisor session."""

    raw_request = input_fn(
        "Requirement: "
    )

    review, questions = advisor.review_request(
        raw_request,
    )

    output_fn(
        format_requirement_review(
            review=review,
            questions=questions,
        )
    )

    while not review.ready_for_confirmation:
        raw_follow_up = input_fn(
            "Follow-up: "
        )

        review, questions = advisor.review_follow_up(
            card=review.card,
            raw_follow_up=raw_follow_up,
        )

        output_fn(
            format_requirement_review(
                review=review,
                questions=questions,
            )
        )

    confirmation = input_fn(
        "Confirm requirements? Type yes to continue: "
    )

    if confirmation.strip().lower() != "yes":
        return None

    confirmed = advisor.confirm(
        review.card,
    )

    result = advisor.recommend(
        database_path=database_path,
        knowledge_base_version=knowledge_base_version,
        requirements=confirmed,
        policy=policy,
    )

    output_fn(
        format_recommendation_result(
            result,
        )
    )

    return result


def main(
    *,
    database_path,
    knowledge_base_version: str,
    model: str,
):
    """Build the default local advisor stack and run one CLI session."""

    parser = OllamaRequirementParser(
        model=model,
    )

    advisor = LocalChipAdvisor(
        parser=parser,
    )

    policy = RankingPolicy(
        criteria=(
            RankingCriterion.CURRENT_HEADROOM,
        ),
    )

    return run_cli_session(
        advisor=advisor,
        database_path=database_path,
        knowledge_base_version=knowledge_base_version,
        policy=policy,
    )


def cli_entrypoint(
    argv: list[str] | None = None,
):
    """Parse command-line arguments and invoke the default CLI stack."""

    parser = argparse.ArgumentParser(
        prog="local-chip-advisor",
    )
    parser.add_argument(
        "--database-path",
        required=True,
    )
    parser.add_argument(
        "--knowledge-base-version",
        required=True,
    )
    parser.add_argument(
        "--model",
        required=True,
    )

    args = parser.parse_args(argv)

    return main(
        database_path=args.database_path,
        knowledge_base_version=args.knowledge_base_version,
        model=args.model,
    )


if __name__ == "__main__":
    cli_entrypoint()
