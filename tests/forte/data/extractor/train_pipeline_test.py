#  Copyright 2020 The Forte Authors. All Rights Reserved.
#  #
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  #
#       http://www.apache.org/licenses/LICENSE-2.0
#  #
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import unittest

from typing import Dict, Any
from torch import Tensor

from forte.data.extractor.converter import Converter
from forte.data.extractor.train_pipeline import TrainPipeline
from forte.data.extractor.trainer import Trainer
from forte.data.readers.conll03_reader_new import CoNLL03Reader
from forte.data.extractor.extractor import TextExtractor, CharExtractor, \
    AnnotationSeqExtractor, BaseExtractor
from ft.onto.base_ontology import Sentence, Token, EntityMention


class TrainPipelineTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "max_char_length": 45,
            "train_path": "data_samples/train_pipeline_test",
            "val_path": "data_samples/train_pipeline_test",
            "num_epochs": 1,
            "batch_size_tokens": 5,
            "learning_rate": 0.01,
            "momentum": 0.9,
            "nesterov": True
        }

        self.request = {
            "scope": Sentence,
            "schemes": {
                "text_tag": {
                    "entry": Token,
                    "repr": "text_repr",
                    "conversion_method": "indexing",
                    "vocab_use_pad": True,
                    "extractor": TextExtractor
                },
                "char_tag": {
                    "entry": Token,
                    "repr": "char_repr",
                    "conversion_method": "indexing",
                    "max_char_length": self.config['max_char_length'],
                    "vocab_use_pad": True,
                    "extractor": CharExtractor
                },
                "ner_tag": {
                    "entry": EntityMention,
                    "attribute": "ner_type",
                    "based_on": Token,
                    "strategy": "BIO",
                    "conversion_method": "indexing",
                    "vocab_use_pad": True,
                    "extractor": AnnotationSeqExtractor
                }
            }
        }

        def create_model_fn(schemes: Dict[str, Dict[str, Any]]):
            pass

        def create_optim_fn(model):
            pass

        def create_criterion_fn(model):
            pass

        def train_forward_fn(model,
                             tensors: Dict[str, Dict[str, Tensor]]):
            pass

        self.create_model_fn = create_model_fn
        self.create_optim_fn = create_optim_fn
        self.train_forward_fn = train_forward_fn

        self.reader = CoNLL03Reader()

        self.trainer = Trainer(create_model_fn=create_model_fn,
                               create_optim_fn=create_optim_fn,
                               create_criterion_fn=create_criterion_fn,
                               train_forward_fn=train_forward_fn)

        config = {
            "data_pack": {
                "train_loader": {
                    "src_dir": self.config["train_path"],
                    "cache": False
                },
                "val_loader": {
                    "src_dir": self.config["val_path"],
                    "cache": False
                }
            },
            "train": {
                "num_epochs": self.config["num_epochs"]
            },
            "dataset": {
                "batch_size": self.config["batch_size_tokens"]
            }
        }

        self.train_pipeline = \
            TrainPipeline(train_reader=self.reader,
                          val_reader=self.reader,
                          trainer=self.trainer,
                          predictor=None,
                          evaluator=None,
                          config=config)

        # TODO: calculate expected loss

    def test_parse_request(self):
        self.train_pipeline._parse_request(self.request)
        self.assertTrue(self.train_pipeline.feature_resource is not None)
        self.assertTrue("scope" in self.train_pipeline.feature_resource)
        self.assertTrue("schemes" in self.train_pipeline.feature_resource)

        self.assertTrue(len(self.train_pipeline.feature_resource["schemes"]),
                        3)
        self.assertTrue(
            "text_tag" in self.train_pipeline.feature_resource["schemes"])
        self.assertTrue(
            "char_tag" in self.train_pipeline.feature_resource["schemes"])
        self.assertTrue(
            "ner_tag" in self.train_pipeline.feature_resource["schemes"])

        for tag, scheme in \
                self.train_pipeline.feature_resource["schemes"].items():
            self.assertTrue("extractor" in scheme)
            self.assertTrue("converter" in scheme)
            self.assertTrue(issubclass(type(scheme["extractor"]),
                                       BaseExtractor))
            self.assertTrue(isinstance(scheme["converter"], Converter))

        # TODO: test invalid request

    def test_build_vocab(self):
        self.train_pipeline._parse_request(self.request)

        self.train_pipeline._build_vocab()

        schemes: Dict[str, Any] = \
            self.train_pipeline.feature_resource["schemes"]

        text_extractor: TextExtractor = schemes["text_tag"]["extractor"]
        self.assertTrue(text_extractor.has_key("EU"))
        self.assertTrue(text_extractor.has_key("Peter"))

        char_extractor: CharExtractor = schemes["char_tag"]["extractor"]
        self.assertTrue(char_extractor.has_key("a"))
        self.assertTrue(char_extractor.has_key("b"))
        self.assertTrue(char_extractor.has_key("."))

        ner_extractor: AnnotationSeqExtractor = schemes["ner_tag"]["extractor"]
        self.assertTrue(ner_extractor.has_key(("PER", "B")))
        self.assertTrue(ner_extractor.has_key((None, "O")))
        self.assertTrue(ner_extractor.has_key(("MISC", "I")))

    def test_build_train_dataset_iterator(self):
        self.train_pipeline._parse_request(self.request)
        self.train_pipeline._build_vocab()

        train_iterator = \
            self.train_pipeline._build_dataset_iterator(
                self.train_pipeline._train_data_pack_loader)

        batchs = []
        for batch in train_iterator:
            batchs.append(batch)

        self.assertEqual(len(batchs), 2)
        self.assertEqual(batchs[0].batch_size, 5)
        self.assertEqual(batchs[1].batch_size, 2)

        for batch in batchs:
            self.assertTrue(hasattr(batch, "text_tag"))
            self.assertTrue(hasattr(batch, "char_tag"))
            self.assertTrue(hasattr(batch, "ner_tag"))

            for tag, tensors in batch.items():
                self.assertTrue("tensor" in tensors)
                self.assertEqual(type(tensors["tensor"]), Tensor)
                self.assertTrue("mask" in tensors)
                if tag == "text_tag" or tag == "ner_tag":
                    self.assertEqual(len(tensors["mask"]), 1)
                    self.assertEqual(type(tensors["mask"][0]), Tensor)
                else:
                    self.assertEqual(len(tensors["mask"]), 2)
                    self.assertEqual(type(tensors["mask"][0]), Tensor)
                    self.assertEqual(type(tensors["mask"][1]), Tensor)

    # TODO: add a test for testing TrainPipeline::run


if __name__ == '__main__':
    unittest.main()
