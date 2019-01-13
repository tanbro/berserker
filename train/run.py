import os
import tensorflow as tf
from input import input_fn_builder
from tqdm import tqdm
import sys

flags = tf.flags
FLAGS = flags.FLAGS

# flags.DEFINE_string("output_dir", "model", "The output directory.")
flags.DEFINE_string("assets_dir", "assets", "The assets directory generated by assets.py.")
flags.DEFINE_string("checkpoint_dir", 'ckpt', "The directory for storing model check points.")
flags.DEFINE_string("gs_bert_model_ch_dir", 'gs://berserker/repo/assets/chinese_L-12_H-768_A-12', "A google storage path to unzipped BERT chinese_L-12_H-768_A-12 model.")
flags.DEFINE_string("train_file", "dataset/train_128.tfrecords", "The training file output by dataset.py.")

flags.DEFINE_integer("max_seq_length", 512, "Maximum sequence length.")
flags.DEFINE_integer("batch_size", 64, "The training, validation and prediction batch size.")

flags.DEFINE_bool("do_train", False, "Train the model.")
flags.DEFINE_float("learning_rate", 2e-5, "The learning rate.")
flags.DEFINE_integer("train_steps", 15243//64, "Number of training steps.")
flags.DEFINE_float("warmup_proportion", 0.1, "")
flags.DEFINE_integer("save_checkpoints_steps", 15243//64, "Number of steps to save a checkpoint.")


flags.DEFINE_bool("do_eval", False, "Evaluate the model.")
flags.DEFINE_string("eval_file", "dataset/val_128.tfrecords", "The validation file output by dataset.py.")
flags.DEFINE_integer("eval_steps", 3811//64, "Number of validation steps.")


flags.DEFINE_bool("do_predict", False, "Make prediction.")
flags.DEFINE_string("predict_file", "assets/icwb2-data/pku_test.utf8", "The input file to be tokenized.")
flags.DEFINE_string("predict_output", "pku_pred.utf8", "The output file for tokenized result.")


flags.DEFINE_bool("use_tpu", False, "Use TPU for training.")
flags.DEFINE_integer("num_tpu_cores", 8, "The number of TPU cores.")
flags.DEFINE_string("tpu_name", None, "TPU worker.")

def main(_):
    tf.logging.set_verbosity(tf.logging.INFO)
    # tf.gfile.MakeDirs(FLAGS.output_dir)

    sys.path += [os.path.join(FLAGS.assets_dir, 'bert')]
    from model import model_fn_builder
    import modeling

    model_fn = model_fn_builder(
        bert_config=modeling.BertConfig.from_json_file(
            os.path.join(FLAGS.gs_bert_model_ch_dir, 'bert_config.json')
        ),
        init_checkpoint=os.path.join(FLAGS.gs_bert_model_ch_dir, 'bert_model.ckpt'),
        use_tpu=FLAGS.use_tpu,
        use_one_hot_embeddings=True if FLAGS.use_tpu else False,
        learning_rate=FLAGS.learning_rate,
        num_train_steps=FLAGS.train_steps,
        num_warmup_steps=int(FLAGS.train_steps * FLAGS.warmup_proportion)
    )

    run_config = tf.contrib.tpu.RunConfig(
        cluster=tf.contrib.cluster_resolver.TPUClusterResolver(FLAGS.tpu_name) if FLAGS.use_tpu else None,
        model_dir=FLAGS.checkpoint_dir,
        save_checkpoints_steps=FLAGS.train_steps,
        tpu_config=tf.contrib.tpu.TPUConfig(
            iterations_per_loop=FLAGS.train_steps,
            num_shards=FLAGS.num_tpu_cores,
            per_host_input_for_training=tf.contrib.tpu.InputPipelineConfig.PER_HOST_V2
        )
    )

    estimator = tf.contrib.tpu.TPUEstimator(
        use_tpu=FLAGS.use_tpu,
        model_fn=model_fn,
        config=run_config,
        train_batch_size=FLAGS.batch_size,
        eval_batch_size=FLAGS.batch_size,
        predict_batch_size=FLAGS.batch_size
    )

    tf.logging.info('Setup success...')

    if FLAGS.do_train:
        estimator.train(
            input_fn=input_fn_builder(
                input_file=FLAGS.train_file,
                seq_length=FLAGS.max_seq_length,
                shuffle=True,
                repeat=True,
                drop_remainder=FLAGS.use_tpu
            ),
            steps=FLAGS.train_steps,
        )

    if FLAGS.do_eval:
        estimator.evaluate(
            input_fn=input_fn_builder(
                input_file=FLAGS.eval_file,
                seq_length=FLAGS.max_seq_length,
                shuffle=False,
                repeat=False,
                drop_remainder=FLAGS.use_tpu
            ),
            steps=FLAGS.eval_steps,
        )

    if FLAGS.do_predict:
        from transform import create_tokenizer, text_to_bert_inputs, postprocess, preprocess
        from input import predict_input_fn_builder
        import numpy as np
        tokenizer = create_tokenizer(
            os.path.join(FLAGS.assets_dir, 'chinese_L-12_H-768_A-12', 'vocab.txt')
        )

        import pandas as pd
        texts = pd.read_csv(FLAGS.predict_file, header=None)[0]

        # texts = [
        #     '共同创造美好的新世纪——二○○一年新年贺词',
        #     '（二○○○年十二月三十一日）（附图片1张）',
        #     '女士们，先生们，同志们，朋友们：',
        #     '2001年新年钟声即将敲响。人类社会前进的航船就要驶入21世纪的新航程。中国人民进入了向现代化建设第三步战略目标迈进的新征程。',
        #     '在这个激动人心的时刻，我很高兴通过中国国际广播电台、中央人民广播电台和中央电视台，向全国各族人民，向香港特别行政区同胞、澳门特别行政区同胞和台湾同胞、海外侨胞，向世界各国的朋友们，致以新世纪第一个新年的祝贺！',
        #     '过去的一年，是我国社会主义改革开放和现代化建设进程中具有标志意义的一年。在中国共产党的领导下，全国各族人民团结奋斗，国民经济继续保持较快的发展势头，经济结构的战略性调整顺利部署实施。西部大开发取得良好开端。精神文明建设和民主法制建设进一步加强。我们在过去几年取得成绩的基础上，胜利完成了第九个五年计划。我国已进入了全面建设小康社会，加快社会主义现代化建设的新的发展阶段。',
        #     '面对新世纪，世界各国人民的共同愿望是：继续发展人类以往创造的一切文明成果，克服20世纪困扰着人类的战争和贫困问题，推进和平与发展的崇高事业，创造一个美好的世界。',
        #     '我们希望，新世纪成为各国人民共享和平的世纪。在20世纪里，世界饱受各种战争和冲突的苦难。时至今日，仍有不少国家和地区的人民还在忍受战火的煎熬。中国人民真诚地祝愿他们早日过上和平安定的生活。中国人民热爱和平与自由，始终奉行独立自主的和平外交政策，永远站在人类正义事业的一边。我们愿同世界上一切爱好和平的国家和人民一道，为促进世界多极化，建立和平稳定、公正合理的国际政治经济新秩序而努力奋斗。' * 10
        # ]

        bert_inputs = []
        bert_inputs_lens = []
        SEQ_LENGTH = FLAGS.max_seq_length - 2
        for text in texts:
            while len(text) > 0:
                bert_input = text_to_bert_inputs(text[:SEQ_LENGTH], FLAGS.max_seq_length, tokenizer)
                bert_inputs_lens.append(len(preprocess(text[:SEQ_LENGTH], tokenizer)[0]))
                bert_inputs.append(bert_input)
                text = text[SEQ_LENGTH:]

        # Pad to prediction batch size
        while len(bert_inputs) % FLAGS.batch_size != 0:
            bert_input = text_to_bert_inputs('', FLAGS.max_seq_length, tokenizer)
            bert_inputs_lens.append(len(preprocess('', tokenizer)[0]))
            bert_inputs.append(bert_input)

        tf.logging.info(len(bert_inputs))

        results = estimator.predict(
            input_fn=predict_input_fn_builder(
                bert_inputs=bert_inputs,
                seq_length=FLAGS.max_seq_length,
                tokenizer=tokenizer,
                drop_remainder=FLAGS.use_tpu
            )
        )

        bert_inputs = iter(bert_inputs)
        bert_inputs_lens = iter(bert_inputs_lens)

        with open(FLAGS.predict_output, 'w') as f:
            for text in texts:
                original_text = text
                prediction = np.array([])
                bert_tokens = []

                while len(text) > 0:
                    (input_ids, _, _, _) = next(bert_inputs)
                    bert_inputs_len = next(bert_inputs_lens)
                    result = next(results)
                    prediction = np.concatenate((prediction, result['predictions'][1:1+bert_inputs_len]))
                    bert_tokens += tokenizer.convert_ids_to_tokens(input_ids[1:1+bert_inputs_len])
                    text = text[SEQ_LENGTH:]

                tokenized_text = postprocess(original_text, bert_tokens, prediction, threshold=0.5)
                print(tokenized_text, file=f)
                # tf.logging.info(" Input: %s"%original_text)
                # tf.logging.info("Output: %s"%tokenized_text)


if __name__ == "__main__":
  tf.app.run()
