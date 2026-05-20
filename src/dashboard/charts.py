import plotly.express as px
import plotly.graph_objects as go
from plotly.graph_objects import Figure

_MARGIN = dict(t=20, b=30, l=10, r=10)


def chart_by_type(df) -> Figure:
    fig = px.bar(
        df, x="transaction_type", y="count",
        color="transaction_type", text_auto=True,
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Count", margin=_MARGIN)
    return fig


def chart_by_channel(df) -> Figure:
    fig = px.pie(
        df, names="channel", values="count",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig.update_layout(margin=_MARGIN)
    return fig


def chart_daily_volume(df) -> Figure:
    fig = px.line(
        df, x="date", y="count",
        color_discrete_sequence=["#2563EB"],
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Transactions", margin=_MARGIN)
    return fig


def chart_by_status(df) -> Figure:
    fig = px.pie(
        df, names="status", values="count",
        color_discrete_sequence=px.colors.qualitative.Safe,
    )
    fig.update_layout(margin=_MARGIN)
    return fig


def chart_by_merchant(df) -> Figure:
    fig = px.bar(
        df, x="avg_amount", y="merchant_category",
        orientation="h", text_auto=".2f",
        color="avg_amount", color_continuous_scale="Blues",
    )
    fig.update_layout(
        showlegend=False, coloraxis_showscale=False,
        xaxis_title="Avg Amount (RM)", yaxis_title="",
        margin=_MARGIN,
    )
    return fig


def chart_flagged(df) -> Figure:
    df = df.copy()
    df["label"] = df["is_flagged"].map({True: "Flagged", False: "Normal"})
    fig = px.bar(
        df, x="label", y="count",
        color="label", text_auto=True,
        color_discrete_map={"Flagged": "#EF4444", "Normal": "#22C55E"},
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Count", margin=_MARGIN)
    return fig


def chart_by_currency(df) -> Figure:
    fig = px.pie(
        df, names="currency", values="count",
        color_discrete_sequence=px.colors.qualitative.Vivid,
    )
    fig.update_layout(margin=_MARGIN)
    return fig
