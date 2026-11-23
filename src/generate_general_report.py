"""Generate the general-audience opportunity report from the discovery pipeline."""
from .discover import main
from .pipeline.schema import ProductTrack


if __name__ == "__main__":
    main(default_track=ProductTrack.GENERAL)
