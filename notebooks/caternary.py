import marimo

__generated_with = "0.13.15"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(
        r"""
    ## From Chaos to Clarity: Unlocking Business Value from Poor or Legacy Code

    See the article - https://www.databooth.com.au/posts/caternary/

    #### [DataBooth](https://www.databooth.com.au) - *Grow with Your Data*

    ---
    """
    )
    return


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    import math
    from scipy.optimize import minimize_scalar

    return


@app.cell
def _():
    from local_module.caternary_py.bubble_cosh import Catenary

    return (Catenary,)


@app.cell
def _():
    # --- Constants for constraints ---

    MAX_SPAN_RATIO = 0.6627  # Maximum allowed span as a fraction of diameter for a valid catenary solution (approximate value)
    MIN_DIAMETER = 0.5  # Minimum allowed diameter value for the UI slider (meters)
    MAX_DIAMETER = 2.0  # Maximum allowed diameter value for the UI slider (meters)
    MIN_SPAN = 0.1  # Minimum allowed span value for the UI slider (meters)
    MAX_SPAN = MAX_SPAN_RATIO * MAX_DIAMETER
    return MAX_DIAMETER, MAX_SPAN_RATIO, MIN_DIAMETER, MIN_SPAN


@app.cell
def _(mo):
    mo.md(
        r"""
    ### Interactive Catenary Curve Explorer

    This notebook demonstrates the properties of a **catenary** curve, also known as a "chainette" or "alysoid."  
    A catenary is the shape assumed by a flexible, uniform chain or cable suspended by its ends and acted on only by gravity.

    **References:**

    - [Wikipedia: Catenary](https://en.wikipedia.org/wiki/Catenary)
    - [MathWorld: Catenary](https://mathworld.wolfram.com/Catenary.html)
    """
    )
    return


@app.cell
def _(MAX_DIAMETER, MIN_DIAMETER, mo):
    # --- UI controls ---

    diameter = mo.ui.slider(
        start=MIN_DIAMETER,
        stop=MAX_DIAMETER,
        value=1.0,
        step=0.01,
        label="Diameter (m)",
    )
    return (diameter,)


@app.cell
def _(MAX_SPAN_RATIO, diameter):
    # Compute the maximum allowable span for the current diameter

    max_span = round(MAX_SPAN_RATIO * diameter.value, 4)
    return (max_span,)


@app.cell
def _(MIN_SPAN, max_span, mo):
    span = mo.ui.slider(
        start=MIN_SPAN,
        stop=max_span,
        value=min(0.6, max_span),
        step=0.01,
        label="Span (m)",
    )
    return (span,)


@app.cell
def _(MAX_SPAN_RATIO, diameter, max_span, mo):
    mo.md(
        f"""
    ### Parameter Constraints

    - The **span** (horizontal distance between endpoints) must not exceed **{MAX_SPAN_RATIO:.2f} × diameter** (vertical distance between endpoints).
    - For the current diameter (**{diameter.value:.2f} m**), the maximum allowed span is **{max_span:.4f} m**.
    - This limit is based on practical engineering guidelines for safe and realistic catenary curves, not a strict mathematical maximum.
    - Horizontal distance between endpoints. Must be less than {MAX_SPAN_RATIO:.2f} times the diameter.
    - Vertical distance between endpoints. Must be positive.

    ### References

    - [Wikipedia: Catenary](https://en.wikipedia.org/wiki/Catenary)  
    - [Engineering practice for catenary sag](https://jlengineering.net/blog/wp-content/uploads/2018/02/Aerial-Power-Cables.pdf)

    ### Interactive Visualisation

    Adjust the sliders for **Diameter** and **Span** to see how the catenary curve changes.
    """
    )
    return


@app.cell
def _(Catenary, diameter, mo, span):
    # --- Try to compute catenary ---

    try:
        catenary = Catenary(diameter.value, span.value)
        a, b = catenary.fit_parameters()

    except Exception as e:
        mo.md(f"**Error occurred:** {e}")
    return (catenary,)


@app.cell
def _(diameter, mo, span):
    # --- Show controls stacked ---

    mo.hstack([diameter, span])
    return


@app.cell
def _(catenary):
    catenary.plot(x_range=(-0.2, 1.4), y_range=(0.0, 1.2))
    return


@app.cell
def _(catenary, mo):
    mo.md(catenary.describe())
    return


if __name__ == "__main__":
    app.run()
