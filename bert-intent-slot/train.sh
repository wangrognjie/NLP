#!/bin/zsh
python train.py\
  --cuda_devices 0\
  --model_path "/Users/wangrongjie/PycharmProjects/bert-base-chinese"\
  --train_data_path "./data/SMP2019/data.json"\
  --intent_label_path "./data/SMP2019/intent_labels.txt"\
  --slot_label_path "./data/SMP2019/slot_labels.txt"\
  --save_dir "./save_model/"\
  --batch_size 64\
  --train_epochs 10
