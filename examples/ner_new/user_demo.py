#  Copyright 2020 The Forte Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import numpy as np
import torch
from texar.torch.data import Batch
from torch import Tensor
from torch.optim import SGD
import yaml
from typing import Dict, Any

from forte.data.types import DATA_INPUT, DATA_OUTPUT
from forte.common.configuration import Config
from forte.data.extractor.extractor import \
    AnnotationSeqExtractor, TextExtractor, CharExtractor, BaseExtractor
from forte.data.extractor.trainer import Trainer
from forte.data.extractor.train_pipeline import TrainPipeline
from forte.models.ner.utils import load_glove_embedding
from forte.models.ner.model_factory import BiRecurrentConvCRF
from forte.data.readers.conll03_reader_new import CoNLL03Reader
from ft.onto.base_ontology import Sentence, Token, EntityMention


if __name__ == "__main__":
    # All the configs
    config_data = yaml.safe_load(open("configs/config_data.yml", "r"))
    config_model = yaml.safe_load(open("configs/config_model.yml", "r"))
    config_preprocess = \
        yaml.safe_load(open("configs/config_preprocessor.yml", "r"))

    config = Config({}, default_hparams=None)
    config.add_hparam('config_data', config_data)
    config.add_hparam('config_model', config_model)
    config.add_hparam('preprocessor', config_preprocess)

    device = torch.device("cuda") if torch.cuda.is_available() \
        else torch.device("cpu")


    def construct_word_embedding_table(embed_dict, extractor: BaseExtractor):
        embedding_dim = list(embed_dict.values())[0].shape[-1]

        scale = np.sqrt(3.0 / embedding_dim)
        table = np.empty(
            [extractor.size(), embedding_dim], dtype=np.float32
        )
        oov = 0
        for word, index in extractor.items():
            if word in embed_dict:
                embedding = embed_dict[word]
            elif word.lower() in embed_dict:
                embedding = embed_dict[word.lower()]
            else:
                embedding = np.random.uniform(
                    -scale, scale, [1, embedding_dim]
                ).astype(np.float32)
                oov += 1
            table[index, :] = embedding
        return torch.from_numpy(table)


    def create_model_fn(schemes: Dict[str, Dict[str, BaseExtractor]]):
        text_extractor: BaseExtractor = schemes["text_tag"]["extractor"]

        # embedding_dict = \
        #     load_glove_embedding(config.preprocessor.embedding_path)
        #
        # for word in embedding_dict:
        #     if not text_extractor.contains(word):
        #         text_extractor.add_entry(word)
        #

        # TODO: temporarily make fake pretrained emb for debugging
        embedding_dict = {}
        fake_tensor = torch.tensor([0.0 for i in range(100)])
        for word, index in text_extractor.items():
            embedding_dict[word] = fake_tensor

        word_embedding_table = \
            construct_word_embedding_table(embedding_dict, text_extractor)

        model = \
            BiRecurrentConvCRF(word_embedding_table=word_embedding_table,
                               char_vocab_size=text_extractor.size(),
                               tag_vocab_size=text_extractor.size(),
                               config_model=config.config_model)
        model.to(device=device)

        return model


    def create_optim_fn(model):
        optim = SGD(
            model.parameters(), lr=config.config_model.learning_rate,
            momentum=config.config_model.momentum, nesterov=True)
        return optim


    def pass_tensor_to_model_fn(model, batch: Batch):
        word = batch["text_tag"]["tensor"]
        char = batch["char_tag"]["tensor"]
        ner = batch["ner_tag"]["tensor"]
        word_masks = batch["text_tag"]["mask"][0]

        loss = model(word, char, ner, mask=word_masks)

        return loss


    reader = CoNLL03Reader()

    trainer = Trainer(create_model_fn=create_model_fn,
                      create_optim_fn=create_optim_fn,
                      pass_tensor_to_model_fn=pass_tensor_to_model_fn)

    # TODO:
    evaluator = None

    train_pipeline = \
        TrainPipeline(train_reader=reader,
                      dev_reader=reader,
                      trainer=trainer,
                      train_path=config.config_data.train_path,
                      evaluator=evaluator,
                      val_path=config.config_data.val_path,
                      num_epochs=config.config_data.num_epochs,
                      batch_size=config.config_data.batch_size_tokens)

    data_request = {
        "scope": Sentence,
        "schemes": {
            "text_tag": {
                "entry": Token,
                "repr": "text_repr",
                "conversion_method": "indexing",
                "vocab_use_pad": True,
                "type": DATA_INPUT,
                "extractor": TextExtractor
            },
            "char_tag": {
                "entry": Token,
                "repr": "char_repr",
                "conversion_method": "indexing",
                "max_char_length": config.config_data.max_char_length,
                "vocab_use_pad": True,
                "type": DATA_INPUT,
                "extractor": CharExtractor
            },
            "ner_tag": {
                "entry": EntityMention,
                "attribute": "ner_type",
                "based_on": Token,
                "strategy": "BIO",
                "conversion_method": "indexing",
                "vocab_use_pad": True,
                "type": DATA_OUTPUT,
                "extractor": AnnotationSeqExtractor
            }
        }
    }

    train_pipeline.run(data_request=data_request)