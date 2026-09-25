# Reference decisions: pilot-diffusers

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-diffusers
> Lines starting with ">" are written by the tool and ignored. Replace each "pending". Indent a wrapped line by two spaces to continue the value above it.
> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.
> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".
> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:". Anchors: replaces the proposed list; repeat each proposed anchor you keep.

Candidate: pilot-diffusers.json 515f2356689f971ca06985157529adf60777d95fd852c520968570c330737b5b
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Use the README's Stable Diffusion v1-4 Naruto full fine-tuning command.
> Entrypoints: examples/text_to_image/README.md; examples/text_to_image/train_text_to_image.py
> Arguments: --mixed_precision=fp16; --pretrained_model_name_or_path=CompVis/stable-diffusion-v1-4; --dataset_name=lambdalabs/naruto-blip-captions; --use_ema; --resolution=512; --center_crop; --random_flip; --train_batch_size=1; --gradient_accumulation_steps=4; --gradient_checkpointing; --max_train_steps=15000; --learning_rate=1e-05; --max_grad_norm=1; --lr_scheduler=constant; --lr_warmup_steps=0; --output_dir=sd-naruto-model
> accept, or replace and also write Description, Entrypoints, Arguments and Reason
Decision: pending

## Fact diff-scenario
> Claim: The selected README command fine-tunes CompVis/stable-diffusion-v1-4 on lambdalabs/naruto-blip-captions with EMA and writes sd-naruto-model.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/README.md:59-74
Decision: pending

## Fact diff-components
> Claim: The VAE and text encoder are frozen while the UNet is put in training mode.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:628-631
Decision: pending

## Fact diff-optimizer
> Claim: The selected default optimizer path constructs AdamW over UNet parameters only.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:720-730
Decision: pending

## Fact diff-columns
> Claim: For the selected Naruto dataset, source maps the image and caption columns to image and text.
> Basis: observed. Essential: no. Anchors: examples/text_to_image/train_text_to_image.py:64-66
Decision: pending

## Fact diff-preprocess
> Claim: Images are resized to 512, center-cropped, randomly flipped, converted to tensors, and normalized; captions are tokenized to fixed model maximum length.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:794-815
Decision: pending

## Fact diff-latents
> Claim: The VAE encodes pixel tensors to sampled latents and scales them by the VAE scaling factor.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:967-969
Decision: pending

## Fact diff-noising
> Claim: Training samples Gaussian noise and random scheduler timesteps, then adds that noise to latents through the scheduler.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:971-990
Decision: pending

## Fact diff-conditioning
> Claim: The frozen text encoder produces hidden states from token IDs, and the UNet receives noisy latents, timesteps, and those hidden states.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:992-993; examples/text_to_image/train_text_to_image.py:1019-1020
Decision: pending

## Fact diff-target
> Claim: Because the command does not set prediction_type and the pretrained scheduler config is not present locally, whether the target is epsilon noise or scheduler velocity remains unresolved; the source supports both branches.
> Basis: unresolved. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:995-1005
Decision: pending

## Fact diff-loss-update
> Claim: The default loss is mean MSE; Accelerate backpropagates it, clips synchronized UNet gradients, and steps optimizer and learning-rate scheduler.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:1022-1023; examples/text_to_image/train_text_to_image.py:1045-1051
Decision: pending

## Fact diff-ema
> Claim: After synchronized optimizer updates, EMA is advanced from UNet parameters; final saving copies EMA parameters into the UNet.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:1053-1058; examples/text_to_image/train_text_to_image.py:1120-1123
Decision: pending

## Fact diff-validation
> Claim: This selected command supplies no validation_prompts, so periodic validation and final inference branches are skipped.
> Basis: observed. Essential: no. Anchors: examples/text_to_image/train_text_to_image.py:1098-1100; examples/text_to_image/train_text_to_image.py:1135-1138
Decision: pending

## Fact diff-save
> Claim: The final artifact is a StableDiffusionPipeline assembled with the text encoder, VAE, and trained UNet and saved to output_dir.
> Basis: observed. Essential: yes. Anchors: examples/text_to_image/train_text_to_image.py:1125-1133
Decision: pending

## Unknown diffusers-u01
> The pinned source does not contain the external CompVis/stable-diffusion-v1-4 scheduler config, so its prediction_type is unresolved.
Decision: pending
Runs must state:

## Unknown diffusers-u02
> Dataset contents, pretrained weights/configs, downloads, and framework internals are external and uninspected.
Decision: pending
Runs must state:

## Unknown diffusers-u03
> No runtime outputs or generated images were inspected.
Decision: pending
Runs must state:

## Non-defect diffusers-n01
> Absence of validation output in this scenario follows from omitting validation_prompts in the selected README command.
Decision: pending

## Non-defect diffusers-n02
> Frozen VAE and text encoder are intentional; the optimizer targets the UNet.
Decision: pending

> Omitted fact: add "## Added fact diffusers-h01" with Wording, Basis, Essential, Anchors and Reason.
> Omitted unknown: add "## Added unknown diffusers-hu01" with Wording, Runs must state and Reason.
> Real defect: add "## Defect diffusers-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
