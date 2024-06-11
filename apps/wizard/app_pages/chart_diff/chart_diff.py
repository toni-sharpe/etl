import datetime as dt
from typing import List, Optional

import pandas as pd
import streamlit as st
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from etl import grapher_model as gm


class ChartDiff:
    # Chart in source environment
    source_chart: gm.Chart
    # Chart in target environment (if new in source environment, there won't be one)
    target_chart: Optional[gm.Chart]
    # Three state: 'approved', 'pending', 'rejected'
    approval_status: gm.CHART_DIFF_STATUS | str
    # DataFrame for all variables with columns dataChecksum and metadataChecksum
    # If True, then the checksum has changed
    modified_checksum: Optional[pd.DataFrame]

    def __init__(
        self,
        source_chart: gm.Chart,
        target_chart: Optional[gm.Chart],
        approval_status: gm.CHART_DIFF_STATUS | str,
        modified_checksum: Optional[pd.DataFrame] = None,
    ):
        self.source_chart = source_chart
        self.target_chart = target_chart
        self.approval_status = approval_status
        if target_chart:
            assert source_chart.id == target_chart.id, "Missmatch in chart ids between Target and Source!"
        self.chart_id = source_chart.id
        self._in_conflict = None
        self.modified_checksum = modified_checksum

    @property
    def is_reviewed(self) -> bool:
        """Check if chart has been reviewed (approved or rejected)."""
        return self.is_approved or self.is_rejected

    @property
    def is_approved(self) -> bool:
        """Check if chart has been approved."""
        return self.approval_status == gm.ChartStatus.APPROVED.value

    @property
    def is_rejected(self) -> bool:
        """Check if the chart has been rejected."""
        return self.approval_status == gm.ChartStatus.REJECTED.value

    @property
    def is_pending(self) -> bool:
        """Check if the chart has status pending."""
        return self.approval_status == gm.ChartStatus.PENDING.value

    @property
    def is_modified(self) -> bool:
        """Check if the chart is a modification from an existing one in target."""
        return self.target_chart is not None

    @property
    def is_new(self) -> bool:
        """Check if the chart in source is new (compared to target)."""
        return not self.is_modified

    @property
    def is_draft(self) -> bool:
        """Check if the chart is a draft."""
        return self.source_chart.publishedAt is None

    @property
    def latest_update(self) -> dt.datetime:
        """Get latest time of change (either be staging or live)."""
        if self.target_chart is None:
            return self.source_chart.updatedAt
        else:
            return max([self.source_chart.updatedAt, self.target_chart.updatedAt])

    @property
    def slug(self) -> str:
        """Get slug of the chart.

        If slug of the chart miss-matches between target and source sessions, an error is displayed.
        """
        if self.target_chart:
            assert self.source_chart.config["slug"] == self.target_chart.config["slug"], "Slug mismatch!"
        return self.source_chart.config.get("slug", "no-slug")

    @property
    def in_conflict(self) -> bool:
        """Check if the chart in target is newer than the source."""
        if self._in_conflict is None:
            if self.target_chart is None:
                return False
            self._in_conflict = self.target_chart.updatedAt > self.source_chart.updatedAt
        return self._in_conflict

    @classmethod
    def from_chart_id(cls, chart_id, source_session: Session, target_session: Optional[Session] = None):
        """Get chart diff from chart id.

        - Get charts from source and target
        - Get its approval state
        - Build diff object
        """
        # Get charts
        source_chart = gm.Chart.load_chart(source_session, chart_id=chart_id)
        if target_session is not None:
            try:
                target_chart = gm.Chart.load_chart(target_session, chart_id=chart_id)
            except NoResultFound:
                target_chart = None
        else:
            target_chart = None

        # It can happen that both charts have the same ID, but are completely different (this
        # happens when two charts are created independently on two servers). If they
        # have same createdAt then they are the same chart.
        if target_chart and source_chart.createdAt != target_chart.createdAt:
            target_chart = None

        # Checks
        if target_chart:
            assert source_chart.createdAt == target_chart.createdAt, "CreatedAt mismatch!"

        # Get approval status
        approval_status = gm.ChartDiffApprovals.latest_chart_status(
            source_session,
            chart_id,
            source_chart.updatedAt,
            target_chart.updatedAt if target_chart else None,
        )

        # Load checksums for underlying indicators
        # TODO: is this fast enough for large datasets? maybe we should avoid dataframes at all
        if target_chart and target_session is not None:
            source_df = source_chart.load_variables_checksums(source_session)
            target_df = target_chart.load_variables_checksums(target_session)
            source_df, target_df = source_df.align(target_df)
            modified_checksum = source_df != target_df

            # If checksum has not been filled yet, assume unchanged
            modified_checksum[target_df.isna()] = False
        else:
            modified_checksum = None

        # Build object
        chart_diff = cls(source_chart, target_chart, approval_status, modified_checksum)

        return chart_diff

    def checksum_changes(self) -> list[str]:
        """Return list of chart changes."""
        if self.is_new:
            return []

        changes = []
        if self.modified_checksum is not None:
            if self.modified_checksum["dataChecksum"].any():
                changes.append("data")
            if self.modified_checksum["metadataChecksum"].any():
                changes.append("metadata")
        if self.target_chart and not self.configs_are_equal():
            changes.append("config")
        return changes

    def get_all_approvals(self, session: Session) -> List[gm.ChartDiffApprovals]:
        """Get history of chart diff."""
        # Get history
        history = gm.ChartDiffApprovals.get_all(
            session,
            chart_id=self.chart_id,
        )
        return history

    def sync(self, source_session: Session, target_session: Optional[Session] = None):
        """Sync chart diff."""

        # Synchronize with latest chart from source environment
        self = self.from_chart_id(
            chart_id=self.chart_id,
            source_session=source_session,
            target_session=target_session,
        )

    def approve(self, session: Session) -> None:
        """Approve chart diff."""
        # Update status variable
        self.set_status(session, gm.ChartStatus.APPROVED.value)

    def reject(self, session: Session) -> None:
        """Reject chart diff."""
        # Update status variable
        self.set_status(session, gm.ChartStatus.REJECTED.value)

    def unreview(self, session: Session) -> None:
        """Set chart diff to pending."""
        # Update status variable
        self.set_status(session, gm.ChartStatus.PENDING.value)

    def set_status(self, session: Session, status: gm.CHART_DIFF_STATUS | str) -> None:
        """Update the state of the chart diff."""
        # Only perform action if status changes!
        if self.approval_status != status:
            # Update status variable
            self.approval_status = status

            # Update approval status (in database)
            assert self.chart_id
            if self.is_modified:
                assert self.target_chart
            approval = gm.ChartDiffApprovals(
                chartId=self.chart_id,
                sourceUpdatedAt=self.source_chart.updatedAt,
                targetUpdatedAt=None if self.is_new else self.target_chart.updatedAt,  # type: ignore
                status=self.approval_status,  # type: ignore
            )
            session.add(approval)
            session.commit()

        match status:
            case gm.ChartStatus.APPROVED.value:
                st.toast(f":green[Chart {self.chart_id} has been **approved**]", icon="✅")
            case gm.ChartStatus.REJECTED.value:
                st.toast(f":red[Chart {self.chart_id} has been **rejected**]", icon="❌")
            case gm.ChartStatus.PENDING.value:
                st.toast(f"**Resetting** state for chart {self.chart_id}.", icon=":material/restart_alt:")

    def configs_are_equal(self) -> bool:
        """Compare two chart configs, ignoring version, id and isPublished."""
        assert self.target_chart is not None, "Target chart is None!"
        exclude_keys = ("version", "id", "isPublished", "bakedGrapherURL", "adminBaseUrl", "dataApiUrl")
        config_1 = {k: v for k, v in self.source_chart.config.items() if k not in exclude_keys}
        config_2 = {k: v for k, v in self.target_chart.config.items() if k not in exclude_keys}
        return config_1 == config_2
