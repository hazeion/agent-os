from dataclasses import FrozenInstanceError
import unittest

from task_inputs import normalize_input_selection, validate_selected_files, TaskInputError


def selection_payload(count=1):
    return {'project_id': 'project_garage', 'task_id': 'task_research', 'agent_id': 'agent_research',
            'expected_task_revision': 1, 'expected_input_revision': 0,
            'context_id': 'project_context_' + 'a'*32, 'expected_grant_revision': 1,
            'instructions': 'Keep bicycle access clear.',
            'attachment_ids': ['attachment_' + f'{index:032x}' for index in range(count)]}


class TaskInputContractTests(unittest.TestCase):
    def test_selection_is_immutable_and_does_not_alias_the_request(self):
        payload = selection_payload()
        value = normalize_input_selection(payload)
        payload['attachment_ids'].clear()
        self.assertEqual(len(value.attachment_ids), 1)
        with self.assertRaises(FrozenInstanceError):
            value.instructions = 'Changed'

    def test_widened_authority_missing_fields_and_unsafe_revisions_are_rejected(self):
        baseline = selection_payload()
        invalid = [{**baseline, 'runtime_agent_ref': 'default'},
                   {**baseline, 'expected_grant_revision': True},
                   {**baseline, 'expected_task_revision': 0},
                   {**baseline, 'expected_input_revision': 2**53},
                   {**baseline, 'context_id': '/private/file'},
                   {**baseline, 'attachment_ids': baseline['attachment_ids']*2},
                   {**baseline, 'attachment_ids': None}, selection_payload(9)]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(TaskInputError):
                    normalize_input_selection(value)

    def test_instruction_limit_is_utf8_and_never_truncates(self):
        value = selection_payload(0)
        value['instructions'] = '\U0001f6b2' * 4096
        self.assertEqual(normalize_input_selection(value).instructions, value['instructions'])
        for instructions in (value['instructions']+'x', 'invalid\0text', '\ud800'):
            with self.assertRaises(TaskInputError):
                normalize_input_selection({**value, 'instructions': instructions})

    def test_complete_order_and_adapter_limits_are_required(self):
        selection = normalize_input_selection(selection_payload(8))
        metadata = [{'id': identifier, 'state': 'attached', 'kind': 'text', 'byte_size': 20, 'mime_type': 'text/plain'} for identifier in selection.attachment_ids]
        validate_selected_files(selection, metadata)
        for values in (metadata[:-1], list(reversed(metadata)), [*metadata[:-1], {**metadata[-1], 'state': 'missing'}]):
            with self.assertRaises(TaskInputError):
                validate_selected_files(selection, values)
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata, adapter_file_limit=5)
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata, adapter_file_limit=True)
        self.assertEqual(len(selection.attachment_ids), 8)

    def test_one_image_ceiling_and_verified_size_shape(self):
        selection = normalize_input_selection(selection_payload(2))
        metadata = [{'id': identifier, 'state': 'attached', 'kind': 'image', 'byte_size': 20, 'mime_type': 'image/png'} for identifier in selection.attachment_ids]
        with self.assertRaisesRegex(TaskInputError, 'image_limit'):
            validate_selected_files(selection, metadata)
        metadata[1].update(kind='text', mime_type='text/plain')
        validate_selected_files(selection, metadata)
        with self.assertRaisesRegex(TaskInputError, 'image_limit'):
            validate_selected_files(selection, metadata, adapter_image_limit=0)
        metadata[0]['byte_size'] = True
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)
        metadata[0].update(byte_size=20, kind=[])
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)
        metadata[0].update(kind='image', mime_type=[])
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)
