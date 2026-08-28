"""The dashboard — the experience layer.

One web page per capability. Each page's form fields are that
capability's inputs; its results view is that capability's output. The
dashboard collects the form, calls the capability's `run()`, and renders
what comes back. It holds no domain logic of its own.

See docs/EXPERIENCE.md for the rules and how to add a page.
"""
