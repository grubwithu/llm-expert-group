from app.prompts import first_opening_prompt


def test_first_opening_prompt_requires_a_repository_grounded_project_overview_first():
    prompt = first_opening_prompt("topic", "abc", False)

    assert "Project overview (start here)" in prompt
    assert "Do not begin with the venue, generic uncertainty, or an evidence disclaimer" in prompt
