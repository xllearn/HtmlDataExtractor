def test_pipeline_request_ignores_user_controlled_paths():
    from app import PipelineRequest

    request = PipelineRequest(
        config_key="default",
        config_path="../../secret.yml",
        field_config_path="../../fields.yml",
        template_path="../../template.xlsx",
        llm_config_path="../../llm.yml",
        output_file="../../out.xlsx",
    )

    assert not hasattr(request, "config_path")
    assert not hasattr(request, "field_config_path")
    assert not hasattr(request, "template_path")
    assert not hasattr(request, "llm_config_path")
    assert not hasattr(request, "output_file")


def test_web_task_output_path_is_fixed_to_task_directory():
    from app import PipelineRequest, task_output_path

    path = task_output_path("task-123", PipelineRequest(config_key="default"))

    assert str(path).replace("\\", "/") == "outputs/task-123/result.xlsx"


def test_allowed_config_uses_whitelist_paths():
    from app import ALLOWED_CONFIGS, allowed_config

    config = allowed_config("default")

    assert config == ALLOWED_CONFIGS["default"]
    assert config["config_path"] == "config/db_config.yml"
