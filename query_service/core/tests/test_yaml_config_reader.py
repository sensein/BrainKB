import unittest
from unittest.mock import mock_open, patch
import yaml
from ..shared import read_yaml_config, yaml_config_to_query_dict


class TestYamlConfigFunctions(unittest.TestCase):
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="rapid_release:\n  - name: Query1\n    value: 100\n  - name: Query2\n    value: 200\n",
    )
    def test_read_yaml_config_valid(self, mock_file):
        # Test that valid YAML is loaded correctly
        result = read_yaml_config("fake_path.yaml")
        expected = {
            "rapid_release": [
                {"name": "Query1", "value": 100},
                {"name": "Query2", "value": 200},
            ]
        }
        self.assertEqual(result, expected)

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_read_yaml_config_file_not_found(self, mock_file):
        # Test that a FileNotFoundError is handled correctly
        result = read_yaml_config("non_existent.yaml")
        self.assertEqual(result, {})

    @patch("builtins.open", new_callable=mock_open, read_data="invalid: [")
    def test_read_yaml_config_invalid_yaml(self, mock_file):
        # Test that invalid YAML content is handled correctly
        result = read_yaml_config("invalid.yaml")
        self.assertEqual(result, {})

    def test_yaml_config_to_query_dict_valid(self):
        # Test conversion of valid YAML data to a list of dictionaries
        yaml_data = {
            "rapid_release": [
                {"name": "Query1", "value": 100},
                {"name": "Query2", "value": 200},
            ]
        }
        result = yaml_config_to_query_dict(yaml_data, "rapid_release", "name", "value")
        expected = [{"Query1": 100}, {"Query2": 200}]
        self.assertEqual(result, expected)

    def test_yaml_config_to_query_dict_missing_key(self):
        # Test that a missing key returns an empty list
        yaml_data = {"not_rapid_release": [{"name": "Query1", "value": 100}]}
        result = yaml_config_to_query_dict(yaml_data, "rapid_release", "name", "value")
        self.assertEqual(result, [])

    def test_yaml_config_to_query_dict_key_not_in_item(self):
        # Test that items missing the dict_key_item or dict_value_item are skipped
        yaml_data = {
            "rapid_release": [
                {"name": "Query1", "value": 100},
                {"name": "Query2"},  # Missing value
            ]
        }
        result = yaml_config_to_query_dict(yaml_data, "rapid_release", "name", "value")
        expected = [{"Query1": 100}]
        self.assertEqual(result, expected)

    def test_yaml_config_to_query_dict_empty(self):
        # Test an empty list in YAML data
        yaml_data = {"rapid_release": []}
        result = yaml_config_to_query_dict(yaml_data, "rapid_release", "name", "value")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
