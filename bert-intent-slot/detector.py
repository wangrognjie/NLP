# -*- coding:utf-8 -*-
# @author: 木子川
# @Email:  m21z50c71@163.com
# @VX：fylaicai


import torch
import numpy as np

from transformers import BertTokenizer

from models import JointBert
from labeldict import LabelDict


class JointIntentSlotDetector:
    def __init__(self, model, tokenizer, intent_dict, slot_dict, use_cuda=True):
        self.model = model
        self.tokenizer = tokenizer
        self.intent_dict = intent_dict
        self.slot_dict = slot_dict
        self.device = "cuda" if torch.cuda.is_available() and use_cuda else "mps"
        print(self.device)
        self.model.to(self.device)
        self.model.eval()

    @classmethod
    def from_pretrained(cls, model_path, tokenizer_path, intent_label_path, slot_label_path, **kwargs):
        intent_dict = LabelDict.load_dict(intent_label_path)
        slot_dict = LabelDict.load_dict(slot_label_path)

        tokenizer = BertTokenizer.from_pretrained(tokenizer_path)

        model = JointBert.from_pretrained(
            model_path,
            slot_label_num=len(slot_dict),
            intent_label_num=len(intent_dict))

        return cls(model, tokenizer, intent_dict, slot_dict, **kwargs)

    def _extract_slots_from_labels_for_one_seq(self, input_ids, slot_labels, mask=None):
        results = {}
        unfinished_slots = {}  # dict of {slot_name: slot_value} pairs
        if mask is None:
            mask = [1 for _ in range(len(input_ids))]

        def add_new_slot_value(results, slot_name, slot_value):
            if slot_name == "" or slot_value == "":
                return results
            if slot_name in results:
                results[slot_name].append(slot_value)
            else:
                results[slot_name] = [slot_value]
            return results

        for i, slot_label in enumerate(slot_labels):
            if mask[i] == 0:
                continue
            # 检测槽位的第一字符（B_）开头
            if slot_label[:2] == 'B_':
                slot_name = slot_label[2:]  # 槽位名称 （B_ 后面）
                if slot_name in unfinished_slots:
                    results = add_new_slot_value(results, slot_name, unfinished_slots[slot_name])
                unfinished_slots[slot_name] = self.tokenizer.decode(input_ids[i])
            # 检测槽位的后面字符（I_）开头
            elif slot_label[:2] == 'I_':
                slot_name = slot_label[2:]
                if slot_name in unfinished_slots and len(unfinished_slots[slot_name]) > 0:
                    unfinished_slots[slot_name] += self.tokenizer.decode(input_ids[i])

        for slot_name, slot_value in unfinished_slots.items():
            if len(slot_value) > 0:
                results = add_new_slot_value(results, slot_name, slot_value)
        return results

    def _extract_slots_from_labels(self, input_ids, slot_labels, mask=None):
        """
        input_ids : [batch, seq_len]
        slot_labels : [batch, seq_len]
        mask : [batch, seq_len]
        """
        if isinstance(input_ids[0], int):
            return self._extract_slots_from_labels_for_one_seq(input_ids, slot_labels, mask)

        if mask is None:
            mask = [1 for id_seq in input_ids for _ in id_seq]

        return [
            self._extract_slots_from_labels_for_one_seq(
                input_ids[i], slot_labels[i], mask[i]
            )
            for i in range(len(input_ids))
        ]

    def _predict_slot_labels(self, slot_probs):
        """
        slot_probs : probability of a batch of tokens into slot labels, [batch, seq_len, slot_label_num], numpy array
        """
        slot_ids = np.argmax(slot_probs, axis=-1)
        return self.slot_dict[slot_ids.tolist()]

    def _predict_intent_labels(self, intent_probs):
        """
        intent_labels : probability of a batch of intent ids into intent labels, [batch, intent_label_num], numpy array
        """
        intent_ids = np.argmax(intent_probs, axis=-1)
        # 获取意图的预测类别和对应的置信度
        intent_confidence = intent_probs.max(axis=-1)  # 获取最大置信度（概率）

        # 打印意图的预测结果和置信度
        # print(f"Predicted intent: {intent_ids}, Confidence: {intent_confidence}")
        intent_id = self.intent_dict[intent_ids.tolist()]
        # print(f"Predicted intent: {intent_id}")
        return {"intent_id": intent_id, "intent_confidence": intent_confidence}

    def detect(self, text, str_lower_case=True):
        """
        text : list of string, each string is a utterance from user
        """
        list_input = True

        if isinstance(text, str):
            text = [text]
            list_input = False

        if str_lower_case:
            text = [t.lower() for t in text]

        batch_size = len(text)
        # 编码
        inputs = self.tokenizer(text, padding=True)
        # Bert 推理
        with torch.no_grad():
            outputs = self.model(input_ids=torch.tensor(inputs['input_ids']).long().to(self.device))

        intent_logits = outputs['intent_logits']
        slot_logits = outputs['slot_logits']

        intent_probs = torch.softmax(intent_logits, dim=-1).detach().cpu().numpy()
        slot_probs = torch.softmax(slot_logits, dim=-1).detach().cpu().numpy()
        # 得到槽位标注结果
        slot_labels = self._predict_slot_labels(slot_probs)
        # # 获取槽位的预测类别和对应的置信度（每个词对应一个槽位标签）
        # slot_preds = slot_probs.argmax(axis=-1)  # 获取每个词的最大概率对应的槽位类别
        # slot_confidences = slot_probs.max(axis=-1)  # 获取每个词的最大置信度（概率）
        #
        # # 打印槽位的预测结果和置信度
        # for i, (pred, conf) in enumerate(zip(slot_preds, slot_confidences)):
        #     print(f"Word {i}: Predicted slot: {pred},slot_labels:{slot_labels}, Confidence: {conf}")
        # 得到意图识别结果
        intent_labels = self._predict_intent_labels(intent_probs)
        slot_values = self._extract_slots_from_labels(inputs['input_ids'], slot_labels, inputs['attention_mask'])

        outputs = [{
            'text': text[i],
            'intent': intent_labels.get("intent_id")[i],
            'intent_confidence': intent_labels.get("intent_confidence")[i],
            'slots': slot_values[i]}
            for i in range(batch_size)]

        if not list_input:
            return outputs[0]

        return outputs


if __name__ == '__main__':
    # model_path = '../saved_models/jointbert-SMP2019/model/model_epoch2'
    # tokenizer_path = '../saved_models/jointbert-SMP2019/tokenizer/'
    model_path = 'bert-base-chinese'
    tokenizer_path = 'bert-base-chinese'
    intent_path = 'data/SMP2019/intent_labels.txt'
    slot_path = 'data/SMP2019/slot_labels.txt'
    model = JointIntentSlotDetector.from_pretrained(
        model_path=model_path,
        tokenizer_path=tokenizer_path,
        intent_label_path=intent_path,
        slot_label_path=slot_path
    )

    while True:
        text = input("input: ")
        print(model.detect(text))
