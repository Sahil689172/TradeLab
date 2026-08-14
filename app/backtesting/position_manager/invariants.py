"""Hard position invariants. Fail loudly instead of silently corrupting state."""

from __future__ import annotations

from app.backtesting.position_manager.exceptions import PositionInvariantError
from app.backtesting.position_manager.schemas import Position, PositionSide, PositionStatus


def validate_position(position: Position) -> None:
    """Raise ``PositionInvariantError`` if ``position`` is internally inconsistent."""
    errors: list[str] = []

    if position.side is not PositionSide.LONG:
        errors.append(f"only LONG positions are supported (got {position.side})")

    if position.quantity <= 0:
        errors.append(f"quantity must be > 0 (got {position.quantity})")

    if position.entry_price <= 0:
        errors.append(f"entry_price must be > 0 (got {position.entry_price})")

    if position.current_price <= 0:
        errors.append(f"current_price must be > 0 (got {position.current_price})")

    if position.status is PositionStatus.CLOSED:
        if position.exit_timestamp is None:
            errors.append("CLOSED position must have exit_timestamp")
        if position.exit_price is None:
            errors.append("CLOSED position must have exit_price")
        if position.exit_reason is None:
            errors.append("CLOSED position must have exit_reason")
        if abs(position.unrealized_pnl) > 1e-9:
            errors.append("CLOSED position cannot retain unrealized_pnl")

    if position.status is PositionStatus.OPEN:
        if position.exit_price is not None:
            errors.append("OPEN position cannot have exit_price")
        if position.exit_timestamp is not None:
            errors.append("OPEN position cannot have exit_timestamp")
        if position.exit_reason is not None:
            errors.append("OPEN position cannot have exit_reason")
        if position.exit_order_id:
            errors.append("OPEN position cannot have exit_order_id")

    if position.status is PositionStatus.PARTIALLY_CLOSED:
        if position.exit_reason is not None and position.quantity <= 0:
            errors.append("PARTIALLY_CLOSED position must keep remaining quantity > 0")

    if position.stop_loss is not None:
        if position.stop_loss <= 0:
            errors.append("stop_loss must be > 0 when supplied")
        elif position.side is PositionSide.LONG and position.stop_loss >= position.entry_price:
            errors.append(
                f"long stop_loss must be < entry_price "
                f"({position.stop_loss} !< {position.entry_price})",
            )

    if position.target_1 is not None and position.side is PositionSide.LONG:
        if position.target_1 <= position.entry_price:
            errors.append(
                f"long target_1 must be > entry_price "
                f"({position.target_1} !> {position.entry_price})",
            )

    if (
        position.target_1 is not None
        and position.target_2 is not None
        and position.side is PositionSide.LONG
        and position.target_2 <= position.target_1
    ):
        errors.append(
            f"long target_2 must be > target_1 "
            f"({position.target_2} !> {position.target_1})",
        )

    if position.target_1_hit and position.target_1_hit_timestamp is None:
        errors.append("target_1_hit requires target_1_hit_timestamp")
    if position.target_2_hit and position.target_2_hit_timestamp is None:
        errors.append("target_2_hit requires target_2_hit_timestamp")
    if position.stop_loss_hit and position.stop_loss_hit_timestamp is None:
        errors.append("stop_loss_hit requires stop_loss_hit_timestamp")

    if errors:
        raise PositionInvariantError("; ".join(errors))
