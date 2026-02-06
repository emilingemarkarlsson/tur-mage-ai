from mage_ai.data_preparation.decorators import data_loader, test


@data_loader
def load_data(*args, **kwargs):
    return {"status": "ok"}


@test
def test_output(output, *args) -> None:
    assert output is not None, "Output is undefined"
