__all__ = ["Plot1D", "Plot2D", "Plot3D"]


def __getattr__(name):
    if name == "Plot1D":
        from .plot1d import Plot1D
        return Plot1D
    if name == "Plot2D":
        from .plot2d import Plot2D
        return Plot2D
    if name == "Plot3D":
        from .plot3d import Plot3D
        return Plot3D
    raise AttributeError(name)
