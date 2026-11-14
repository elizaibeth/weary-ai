---
title: "AWS adds OpenFold3-preview to SageMaker JumpStart"
description: "AWS says OpenFold3-preview can be deployed through SageMaker JumpStart in an AWS account, giving research and drug discovery teams managed inference for biomolecular structure prediction."
date: 2026-11-14
draft: false
categories: ["Products"]
tags: ["AWS", "AI biology", "Models"]
image_alt: "A server block connected to a stylized folded biomolecule."
image_caption: "AWS places OpenFold3 inside its managed endpoint"
why_today: "AWS is putting a structure-prediction model into a managed cloud endpoint, making the deployment details and privacy controls the main news."
source_urls: ["https://aws.amazon.com/blogs/machine-learning/openfold3-on-amazon-sagemaker-jumpstart-predict-biomolecular-structures/"]
origin_urls: ["https://aws.amazon.com/blogs/machine-learning/openfold3-on-amazon-sagemaker-jumpstart-predict-biomolecular-structures/"]
---

AWS said it is offering OpenFold3-preview through Amazon SageMaker JumpStart, allowing users to deploy the biomolecular structure prediction model in their own AWS accounts. The model was developed by the OpenFold Consortium and the AlQuraishi Lab at Columbia University.

The company said OpenFold3 can be used to predict the 3D structures of proteins, DNA, RNA, small-molecule ligands and the complexes they form. AWS said the endpoint runs in a managed Amazon SageMaker AI environment with request queuing, GPU warmup and optional autoscaling.

AWS also said the setup uses network isolation and supports customer-provided MSAs, which it says can help keep sequences within an AWS account. The company said asynchronous inference is intended for long-running jobs and bursty batch workloads, while multi-GPU instances can run predictions in parallel.

AWS added that scale-to-zero can stop endpoint-instance charges after the queue has been empty long enough for the service to scale in, though other charges such as Amazon S3 storage still apply. The post says the sample code is for experimentation and should be reviewed with security and legal teams before use with proprietary or regulated data.

## Sources

- [OpenFold3 on Amazon SageMaker JumpStart: Predict biomolecular structures](<https://aws.amazon.com/blogs/machine-learning/openfold3-on-amazon-sagemaker-jumpstart-predict-biomolecular-structures/>)
